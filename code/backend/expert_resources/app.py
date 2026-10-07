"""Local prototype resource service; existing test identity, read-only test data."""
import json
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends, Request
from fastapi.responses import JSONResponse, Response
from fastapi.exceptions import RequestValidationError
from backend.api.envelope import ApiError, ok
from backend.metric_verification.config import load_environment, database_config, environment_name
from .auth import current_actor, require_use, access, can_manage
from . import runtime, store, execution, rules, processing, briefing

load_environment()


@asynccontextmanager
async def lifespan(app):
    # Exclusive ownership precedes migration or recovery, preventing a second
    # instance from interrupting the first instance's legitimate execution.
    processing.acquire()
    try:
        store.initialize()
        rules.initialize()
        execution.initialize()
        processing.initialize()
        briefing.initialize()
        processing.start()
        yield
    finally:
        processing.stop()


app = FastAPI(title='HighEdu Expert Resources', docs_url=None, redoc_url=None, lifespan=lifespan)


@app.exception_handler(ApiError)
async def api_error(request, exc):
    return JSONResponse({'code': exc.code, 'msg': exc.msg, 'data': None}, status_code=exc.status_code)


@app.exception_handler(RequestValidationError)
async def invalid_request(request, exc):
    return JSONResponse({'code': 422, 'msg': '请求字段格式不正确', 'data': None}, status_code=422)


@app.exception_handler(Exception)
async def unavailable(request, exc):
    logging.getLogger(__name__).error('Expert resource operation failed (%s)', type(exc).__name__)
    return JSONResponse({'code': 503, 'msg': '资源服务或数据库暂不可用，请重试；本次操作未确认成功', 'data': None}, status_code=503)


@app.get('/health')
def health():
    return ok({'service': 'expert-resources', 'businessData': 'configured-test-database', 'resourceStore': 'local-sqlite',
               'environment': environment_name(), 'businessAccess': 'read-only',
               'processing': processing.status(),
               'dataSources': {layer: {'database': database_config(layer).database, 'configured': database_config(layer).configured}
                              for layer in ('source', 'analytics')}})


@app.get('/api/admin/expert-resources/access')
def get_access(actor=Depends(current_actor)):
    return ok(access(actor))


def mcp_error(rid, code, message):
    return {'jsonrpc': '2.0', 'id': rid, 'error': {'code': code, 'message': message}}


@app.get('/api/admin/expert-resources/mcp')
def mcp_stream(actor=Depends(current_actor)):
    require_use(actor)
    return Response(status_code=405, headers={'Allow': 'POST'})


@app.post('/api/admin/expert-resources/mcp')
async def mcp(request: Request, actor=Depends(current_actor)):
    """Stateless MCP Streamable HTTP JSON response mode, protocol 2025-06-18.

    Session credentials remain the existing HighEdu bearer/active identity.
    The endpoint exposes only published registered tools, never arbitrary SQL.
    """
    require_use(actor)
    origin = request.headers.get('origin')
    if origin and origin not in {'http://127.0.0.1:3007', 'http://127.0.0.1:3006', 'http://127.0.0.1:8011'}:
        raise ApiError('不接受此来源的MCP请求', code=403, status_code=403)
    if request.headers.get('mcp-protocol-version', '2025-06-18') not in {'2025-06-18', '2025-03-26'}:
        return JSONResponse(mcp_error(None, -32600, '不支持的MCP协议版本'), status_code=400)
    try:
        body = await request.json()
    except ValueError:
        return JSONResponse(mcp_error(None, -32700, 'JSON解析失败'), status_code=400)
    if not isinstance(body, dict) or body.get('jsonrpc') != '2.0' or not isinstance(body.get('method'), str):
        return JSONResponse(mcp_error(None, -32600, '无效JSON-RPC请求'), status_code=400)
    rid, method = body.get('id'), body['method']
    params = body.get('params') or {}
    if not isinstance(params, dict):
        return mcp_error(rid, -32602, '参数必须是对象')
    if 'id' not in body:
        if method == 'notifications/initialized':
            return Response(status_code=202)
        return Response(status_code=400)
    if method == 'initialize':
        data = {'protocolVersion': '2025-06-18', 'capabilities': {'tools': {'listChanged': False}},
                'serverInfo': {'name': 'highedu-education-data', 'version': '1.0.0'}}
    elif method == 'ping':
        data = {}
    elif method in {'tools/list', 'tools/call'}:
        server_id = request.query_params.get('server_id', 'education-data')
        resource = store.get_resource('mcps', server_id, actor)
        if not resource['enabled'] or not resource.get('published'):
            return mcp_error(rid, -32000, '教学数据MCP尚未发布或已停用')
        published = resource['published']['content']
        tool_list = published.get('tools') or []
        if method == 'tools/list':
            data = {'tools': [{k: v for k, v in t.items() if k in {'name', 'title', 'description', 'inputSchema', 'outputSchema', 'annotations'}} for t in tool_list]}
        else:
            name, args = params.get('name'), params.get('arguments', {})
            registered = next((t for t in tool_list if t['name'] == name), None)
            if not registered or not isinstance(args, dict):
                return mcp_error(rid, -32602, '未登记工具或参数无效')
            from jsonschema import Draft202012Validator
            if list(Draft202012Validator(registered['inputSchema']).iter_errors(args)):
                return mcp_error(rid, -32602, '输入不符合工具契约')
            try:
                result = runtime.run_tool(name, args, actor)
                if list(Draft202012Validator(registered.get('outputSchema') or {}).iter_errors(result)):
                    raise ApiError('工具输出未通过契约校验', status_code=409)
                data = {'content': [{'type': 'text', 'text': json.dumps(result, ensure_ascii=False)}],
                        'structuredContent': result, 'isError': result['status'] == 'blocked'}
            except ApiError as exc:
                data = {'content': [{'type': 'text', 'text': exc.msg}], 'isError': True}
    else:
        return mcp_error(rid, -32601, '方法不存在')
    return {'jsonrpc': '2.0', 'id': rid, 'result': data}


from .router import router
app.include_router(router)
from .briefing_router import router as briefing_router
app.include_router(briefing_router)
