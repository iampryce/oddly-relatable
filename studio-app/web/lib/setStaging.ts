// A set's staging in words (Settings > Sets): how many seats, whether the table front is marked. Pure; node --test.
export function stagingSummary(b: any): string {
  const seats = (b?.seats || (b?.seat ? [b.seat] : [])).length;
  return `Staging: ${seats} seat(s)${b?.table_front ? ', table front marked' : ', no table front'}, floor line at ${b?.floor_y ?? '—'} px`;
}
