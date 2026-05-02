declare module 'd3-bboxCollide' {
  type Bounds = [[number, number], [number, number]];
  interface BboxForce {
    iterations(n: number): BboxForce;
    initialize(nodes: unknown[]): void;
    (alpha: number): void;
  }
  export function bboxCollide(bbox: (node: unknown) => Bounds): BboxForce;
}
