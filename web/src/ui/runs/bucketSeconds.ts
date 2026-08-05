// Snap an estimated duration (seconds) to a deliberately coarse bucket label.
// One source of truth shared by the Start modal and the cockpit ticker.
export function bucketSeconds(seconds: number): string {
  if (seconds < 60) return 'under a minute';
  if (seconds < 450) return 'about 5 minutes';
  if (seconds < 1200) return 'about 10 minutes';
  if (seconds < 2700) return 'about 30 minutes';
  if (seconds < 7200) return 'about an hour';
  return 'a few hours';
}
