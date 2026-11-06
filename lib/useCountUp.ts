"use client";

import { useEffect, useRef, useState } from "react";

const DURATION = 600;

/** Eases a displayed number to its target. Jumps straight there under reduced motion. */
export function useCountUp(target: number): number {
  const [value, setValue] = useState(target);
  const from = useRef(0);

  useEffect(() => {
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      setValue(target);
      from.current = target;
      return;
    }
    const start = performance.now();
    const origin = from.current;
    let frame = 0;
    const tick = (now: number) => {
      const progress = Math.min(1, (now - start) / DURATION);
      const eased = 1 - (1 - progress) ** 3;
      setValue(Math.round(origin + (target - origin) * eased));
      if (progress < 1) frame = requestAnimationFrame(tick);
      else from.current = target;
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [target]);

  return value;
}
