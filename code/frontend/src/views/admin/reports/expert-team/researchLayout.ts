/** Leave a small bottom gutter and use the actual app header height at browser zoom. */
export function availableResearchHeight(viewportHeight: number, workspaceTop: number): number {
  return Math.max(0, Math.floor(viewportHeight - Math.max(0, workspaceTop) - 16))
}
