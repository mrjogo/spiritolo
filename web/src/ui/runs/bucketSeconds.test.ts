import { describe, it, expect } from 'vitest';
import { bucketSeconds } from './bucketSeconds';

describe('bucketSeconds', () => {
  it('maps the ladder boundaries', () => {
    expect(bucketSeconds(0)).toBe('under a minute');
    expect(bucketSeconds(59)).toBe('under a minute');
    expect(bucketSeconds(60)).toBe('about 5 minutes');
    expect(bucketSeconds(449)).toBe('about 5 minutes');
    expect(bucketSeconds(450)).toBe('about 10 minutes');
    expect(bucketSeconds(1200)).toBe('about 30 minutes');
    expect(bucketSeconds(2700)).toBe('about an hour');
    expect(bucketSeconds(7200)).toBe('a few hours');
  });
});
