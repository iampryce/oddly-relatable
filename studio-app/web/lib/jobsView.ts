// Production page: "Recent jobs" shows the latest 10; "Show more" shows up to 40.
export function recentRows<T>(jobs: T[], more: boolean): T[] {
  return jobs.slice(0, more ? 40 : 10);
}
