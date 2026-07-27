import type { LocationQueryRaw } from 'vue-router'

type QueryValue = string | number | boolean | null | undefined

export function compactDrillQuery(
  query: Record<string, QueryValue>,
): LocationQueryRaw {
  return Object.fromEntries(
    Object.entries(query).filter(([, value]) => (
      value !== undefined && value !== null && value !== ''
    )),
  ) as LocationQueryRaw
}

export function withReturnContext(
  query: Record<string, QueryValue>,
  returnTo: string,
  returnLabel: string,
): LocationQueryRaw {
  return compactDrillQuery({ ...query, returnTo, returnLabel })
}

export function withScrollPosition(
  query: LocationQueryRaw,
  scrollY = window.scrollY,
): LocationQueryRaw {
  return {
    ...query,
    scrollY: String(Math.max(0, Math.round(scrollY))),
  }
}
