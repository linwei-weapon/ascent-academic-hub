export interface ResultArrival { researchId: string; turnId: string; resultId: string }
export function shouldFollowResult(previous: ResultArrival, next: ResultArrival, state: { loading: boolean; firstRound: boolean; wasAtEnd: boolean; userInteracted: boolean }): boolean {
  if (state.loading || previous.researchId !== next.researchId || !next.resultId) return false
  if (previous.turnId === next.turnId && previous.resultId === next.resultId) return false
  return state.wasAtEnd || (state.firstRound && !state.userInteracted)
}
export function positionConclusion(reader: HTMLElement, conclusion: HTMLElement): boolean {
  if (!reader.contains(conclusion)) return false
  reader.scrollTop = Math.max(0, reader.scrollTop + conclusion.getBoundingClientRect().top - reader.getBoundingClientRect().top - 10)
  return true
}
