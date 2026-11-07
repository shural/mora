import type { Naturalness } from "../types";
import { NATURALNESS_DOT, NATURALNESS_LABEL } from "../types";
import { cn } from "../lib/cn";

export function NaturalnessDot({
  value,
  className,
}: {
  value: Naturalness | null;
  className?: string;
}) {
  return (
    <span
      className={cn("nat-dot", value === null ? "nat--none" : `nat--${value}`, className)}
      aria-hidden="true"
    />
  );
}

export function NaturalnessBadge({ value }: { value: Naturalness | null }) {
  if (value === null) {
    return <span className="nat-badge nat-badge--none">未标注</span>;
  }
  return (
    <span className={cn("nat-badge", `nat-badge--${value}`)}>
      <span className="nat-badge-dot" aria-hidden="true" />
      {NATURALNESS_LABEL[value]}
      <span className="nat-badge-emoji" aria-hidden="true">
        {NATURALNESS_DOT[value]}
      </span>
    </span>
  );
}
