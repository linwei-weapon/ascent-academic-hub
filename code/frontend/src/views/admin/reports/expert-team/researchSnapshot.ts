import type { Research, ResearchResult, ResearchRun, ResearchTurn, SavedText } from '@/utils/expertResearch'

type Run = ResearchRun & { turn_id?: string; created_at?: string; finished_at?: string; lease_generation?: number; retry_of?: string }
type Result = ResearchResult & { created_at?: string }
const time = (value?: string) => value && !Number.isNaN(Date.parse(value)) ? Date.parse(value) : 0
const rank = (status: string) => ['queued', 'pending'].includes(status) ? 1 : status === 'running' ? 2 : ['cancel_requested', 'cancelling'].includes(status) ? 3 : 4
const terminal = (run: Run) => rank(run.status) === 4
function mergeRun(previous: Run, incoming: Run): Run {
  if (previous.id !== incoming.id) {
    if (incoming.retry_of === previous.id) return incoming
    if (previous.retry_of === incoming.id) return previous
    return time(incoming.created_at) > time(previous.created_at) ? incoming : previous
  }
  if (terminal(previous) && !terminal(incoming)) return previous
  if (terminal(incoming) && !terminal(previous)) return incoming
  if (rank(incoming.status) !== rank(previous.status)) return rank(incoming.status) > rank(previous.status) ? incoming : previous
  if ((incoming.lease_generation || 0) !== (previous.lease_generation || 0)) return (incoming.lease_generation || 0) > (previous.lease_generation || 0) ? incoming : previous
  return time(incoming.finished_at) > time(previous.finished_at) ? incoming : previous
}
function mergeTurn(previous: ResearchTurn, incoming: ResearchTurn): ResearchTurn {
  const run = mergeRun(previous.run, incoming.run)
  const result = !previous.result ? incoming.result : !incoming.result ? previous.result : previous.result.id === incoming.result.id ? { ...previous.result, ...incoming.result, method_unavailable: previous.result.method_unavailable || incoming.result.method_unavailable } : time((incoming.result as Result).created_at) > time((previous.result as Result).created_at) ? incoming.result : previous.result
  return { ...previous, ...incoming, run, result }
}
const saved = (previous: SavedText, incoming: SavedText) => incoming.revision > previous.revision ? incoming : previous
function mergeRevisions<T extends { id: string; revision: number }>(previous: T[], incoming: T[]): T[] {
  const items = new Map(previous.map(item => [item.id, item]))
  incoming.forEach(item => { const old = items.get(item.id); if (!old || item.revision > old.revision) items.set(item.id, item) })
  return [...items.values()]
}
function chooseResult(previous: Result | null, incoming: Result | null, turns: ResearchTurn[]): Result | null {
  if (!previous) return incoming
  if (!incoming) return previous
  if (previous.id === incoming.id) return { ...previous, ...incoming, method_unavailable: previous.method_unavailable || incoming.method_unavailable }
  const oldSeq = turns.find(turn => turn.result?.id === previous.id)?.seq, newSeq = turns.find(turn => turn.result?.id === incoming.id)?.seq
  if (oldSeq != null && newSeq != null && oldSeq !== newSeq) return newSeq > oldSeq ? incoming : previous
  return time(incoming.created_at) > time(previous.created_at) ? incoming : previous
}

// Domain revisions are independent. A history page may add turns, but never move the live snapshot backwards.
export function mergeResearchSnapshot(previous: Research, incoming: Research, keepHistoryCursor = false): Research {
  const map = new Map(previous.turns.map(turn => [turn.id, turn]))
  incoming.turns.forEach(turn => map.set(turn.id, map.has(turn.id) ? mergeTurn(map.get(turn.id)!, turn) : turn))
  const turns = [...map.values()].sort((a, b) => a.seq != null && b.seq != null ? a.seq - b.seq : a.created_at.localeCompare(b.created_at))
  const newerContext = incoming.context_epoch > previous.context_epoch, olderContext = incoming.context_epoch < previous.context_epoch
  const frontier = (record: Research) => Math.max(0, ...record.turns.map(turn => turn.seq || 0))
  const header = newerContext || (!olderContext && (time(incoming.updated_at) > time(previous.updated_at) || frontier(incoming) > frontier(previous))) ? incoming : previous
  const currentResult = newerContext ? incoming.current_result : olderContext ? previous.current_result : chooseResult(previous.current_result, incoming.current_result, turns)
  const metadata = incoming.metadata_revision > previous.metadata_revision ? incoming : previous
  const participants = incoming.participants_revision > previous.participants_revision ? incoming : previous
  const latest = turns.at(-1)
  const resultSeq = turns.find(turn => turn.result?.id === currentResult?.id)?.seq
  const candidates = (newerContext ? [incoming.active_run] : olderContext ? [previous.active_run] : [previous.active_run, incoming.active_run, latest?.run]).filter((run): run is Run => !!run)
  const active = new Map<string, Run>()
  for (const candidate of candidates) {
    const turn = turns.find(item => item.run.id === candidate.id || item.id === candidate.turn_id)
    const run = turn?.run.id === candidate.id ? mergeRun(candidate, turn.run) : candidate
    if (terminal(run)) continue
    if (turn?.seq != null && latest?.seq != null && turn.seq < latest.seq) continue
    if (!turn && time(run.created_at) && time(latest?.created_at) > time(run.created_at)) continue
    if (time(run.created_at) && time((currentResult as Result | null)?.created_at) >= time(run.created_at) && (turn?.seq == null || resultSeq == null || resultSeq >= turn.seq)) continue
    active.set(run.id, active.has(run.id) ? mergeRun(active.get(run.id)!, run) : run)
  }
  const activeRun = [...active.values()].sort((a, b) => time(b.created_at) - time(a.created_at))[0] || null
  const materials = new Map(previous.materials.map(item => [item.id, item])); incoming.materials.forEach(item => materials.set(item.id, item))
  return { ...header, context_epoch: Math.max(previous.context_epoch, incoming.context_epoch), updated_at: time(incoming.updated_at) > time(previous.updated_at) ? incoming.updated_at : previous.updated_at,
    title: metadata.title, status: metadata.status, metadata_revision: metadata.metadata_revision,
    participants: participants.participants, participants_revision: participants.participants_revision,
    draft: saved(previous.draft, incoming.draft), opinion: saved(previous.opinion, incoming.opinion),
    turns, current_result: currentResult, active_run: activeRun, questions: mergeRevisions(previous.questions, incoming.questions), materials: [...materials.values()],
    next_before: keepHistoryCursor || header === previous ? previous.next_before : incoming.next_before }
}
