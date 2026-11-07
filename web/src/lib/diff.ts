import type { SingDiffItem } from "../types";

/**
 * Character-level LCS diff used to render the kana comparison in sing-back.
 * `a` is the target character, `b` the character that was heard.
 */
export function diffChars(target: string, heard: string): SingDiffItem[] {
  const a = Array.from(target);
  const b = Array.from(heard);
  const rows = a.length;
  const cols = b.length;

  // lcs[i][j] = length of the LCS of a[i:] and b[j:]
  const lcs: number[][] = Array.from({ length: rows + 1 }, () =>
    new Array<number>(cols + 1).fill(0),
  );
  for (let i = rows - 1; i >= 0; i -= 1) {
    for (let j = cols - 1; j >= 0; j -= 1) {
      const row = lcs[i];
      const nextRow = lcs[i + 1];
      if (row === undefined || nextRow === undefined) continue;
      row[j] = a[i] === b[j] ? (nextRow[j + 1] ?? 0) + 1 : Math.max(nextRow[j] ?? 0, row[j + 1] ?? 0);
    }
  }

  const out: SingDiffItem[] = [];
  let i = 0;
  let j = 0;
  while (i < rows && j < cols) {
    if (a[i] === b[j]) {
      out.push({ op: "eq", a: a[i], b: b[j] });
      i += 1;
      j += 1;
      continue;
    }
    const skipA = lcs[i + 1]?.[j] ?? 0;
    const skipB = lcs[i]?.[j + 1] ?? 0;
    if (skipB >= skipA) {
      out.push({ op: "ins", b: b[j] });
      j += 1;
    } else {
      out.push({ op: "del", a: a[i] });
      i += 1;
    }
  }
  while (i < rows) {
    out.push({ op: "del", a: a[i] });
    i += 1;
  }
  while (j < cols) {
    out.push({ op: "ins", b: b[j] });
    j += 1;
  }
  return out;
}
