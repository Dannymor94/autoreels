import { useState } from "react";
import { persist, type SizeMode } from "./persist";

/** Pixel values per scale. Source rows use thumbH; the overview grid uses cardMin. */
export const SIZES: Record<SizeMode, { thumbH: number; cardMin: number }> = {
  s: { thumbH: 48, cardMin: 110 },
  m: { thumbH: 88, cardMin: 150 },
  l: { thumbH: 160, cardMin: 220 },
};

/** Shared, remembered scale. */
export function useSize(): [SizeMode, (v: SizeMode) => void] {
  const [size, setState] = useState<SizeMode>(() => persist.size());
  return [
    size,
    (v: SizeMode) => {
      persist.setSize(v);
      setState(v);
    },
  ];
}
