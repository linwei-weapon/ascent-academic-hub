"""Bounded ZIP inspection. Uploaded scripts are stored as evidence, never executed."""
import base64
import io
import re
import stat
import zipfile
from pathlib import PurePosixPath

from backend.api.envelope import ApiError


def inspect_package(filename, encoded):
    def fail(msg):
        raise ApiError(msg, status_code=422)
    if not filename.lower().endswith('.zip'):
        fail('请上传 ZIP 技能包')
    try:
        raw = base64.b64decode(encoded, validate=True)
    except Exception:
        fail('技能包编码无效')
    if len(raw) > 2_000_000:
        fail('技能包不能超过2MB')
    files = []
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            entries = archive.infolist()
            if len(entries) > 100 or sum(e.file_size for e in entries) > 1_500_000:
                fail('技能包最多100个文件，解压内容不超过1.5MB')
            seen = set()
            for entry in entries:
                name = entry.filename
                if not entry.flag_bits & 0x800:
                    try:
                        name = name.encode('cp437').decode('gbk')
                    except (UnicodeError, LookupError):
                        pass
                name = name.replace('\\', '/')
                parts = PurePosixPath(name).parts
                if not parts or name.startswith('/') or ':' in name or '..' in parts or any(ord(c) > 127 for c in name):
                    fail('文件路径必须为ASCII相对路径，不能包含上级目录：' + name)
                if stat.S_ISLNK(entry.external_attr >> 16) or entry.flag_bits & 1:
                    fail('技能包不能包含符号链接或加密文件')
                if entry.is_dir() or name.endswith('/'):
                    continue
                normalized = str(PurePosixPath(name))
                if normalized in seen:
                    fail('技能包存在重复路径：' + normalized)
                seen.add(normalized)
                data = archive.read(entry)
                if len(data) > 120_000:
                    fail('单文件不能超过120KB：' + normalized)
                item = {'path': normalized, 'size': len(data)}
                try:
                    item['text'] = data.decode('utf-8-sig')
                except UnicodeError:
                    fail('当前技能包只支持UTF-8文本文件，无法保存二进制内容：' + normalized)
                files.append(item)
    except (zipfile.BadZipFile, RuntimeError, OSError):
        fail('ZIP文件损坏或不可读取')
    candidates = [f for f in files if f['path'] == 'SKILL.md' or f['path'].count('/') == 1 and f['path'].endswith('/SKILL.md')]
    if len(candidates) != 1:
        fail('SKILL.md必须位于根目录或唯一子目录根，且只出现一次')
    skill = candidates[0]
    root = skill['path'].removesuffix('SKILL.md')
    if root and any(not f['path'].startswith(root) for f in files):
        fail('技能包必须只有一个技能根目录')
    text = skill.get('text', '')
    match = re.match(r'\A---\s*\n(.*?)\n---(?:\s*\n|\s*$)', text, re.S)
    if not match:
        fail('SKILL.md缺少front matter')
    metadata = {}
    lines = match.group(1).splitlines()
    for index, line in enumerate(lines):
        found = re.match(r'^(name|version|description):\s*(.*)$', line)
        if not found:
            continue
        key, value = found.groups()
        if key in metadata:
            fail('front matter字段重复：' + key)
        if value in {'|', '>', '|-', '>-'}:
            collected = []
            for following in lines[index + 1:]:
                if following and not following[0].isspace():
                    break
                collected.append(following.strip())
            value = ('\n' if value.startswith('|') else ' ').join(collected)
        metadata[key] = value.strip().strip('"\'')
    if any(not metadata.get(k) for k in ('name', 'version', 'description')):
        fail('front matter必须包含非空name、version和description')
    if not re.fullmatch(r'[a-z][a-z0-9_-]{0,99}', metadata['name']):
        fail('技能name必须为小写字母开头的稳定标识')
    if not re.fullmatch(r'\d+\.\d+\.\d+(?:-[a-zA-Z0-9.-]+)?', metadata['version']):
        fail('技能version必须为语义版本，例如1.0.0')
    if len(metadata['description']) > 4000:
        fail('技能description不能超过4000字符')
    package = {'filename': filename, 'frontMatter': metadata, 'files': files,
               'skillType': 'code' if any(f['path'].endswith(('.py', '.js', '.sh', '.ps1')) for f in files) else 'prompt',
               'warnings': ['文件仅解析和保存，上传脚本不会自动运行；发布前需接入执行器并完成测试',
                            '仅解析name、version、description及缩进多行描述；其他front matter保留在SKILL.md原文中，不自动建立依赖',
                            '技能类型根据脚本文件名生成候选，需在基本信息中确认']}
    import json
    if len(json.dumps(package, ensure_ascii=False).encode('utf-8')) > 150_000:
        fail('技能包预览内容不能超过150KB')
    return package
