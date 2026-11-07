import type { ReactNode } from "react";

interface IconProps {
  size?: number;
  className?: string;
}

const strokeProps = {
  viewBox: "0 0 24 24",
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 1.7,
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const,
  "aria-hidden": true,
  focusable: false,
};

function StrokeIcon({
  size = 20,
  className,
  children,
  viewBox = "0 0 24 24",
}: IconProps & { children: ReactNode; viewBox?: string }) {
  return (
    <svg {...strokeProps} viewBox={viewBox} width={size} height={size} className={className}>
      {children}
    </svg>
  );
}

export function IconPlay({ size = 20, className }: IconProps) {
  return (
    <svg
      viewBox="0 0 24 24"
      width={size}
      height={size}
      className={className}
      aria-hidden
      focusable={false}
    >
      <path d="M8.5 5.6a.8.8 0 0 1 1.2-.7l9.1 6.4a.8.8 0 0 1 0 1.4l-9.1 6.4a.8.8 0 0 1-1.2-.7z" fill="currentColor" />
    </svg>
  );
}

export function IconPause({ size = 20, className }: IconProps) {
  return (
    <svg
      viewBox="0 0 24 24"
      width={size}
      height={size}
      className={className}
      aria-hidden
      focusable={false}
    >
      <rect x="7" y="5.5" width="3.4" height="13" rx="1.2" fill="currentColor" />
      <rect x="13.6" y="5.5" width="3.4" height="13" rx="1.2" fill="currentColor" />
    </svg>
  );
}

export function IconBack({ size = 20, className }: IconProps) {
  return (
    <StrokeIcon size={size} className={className}>
      <path d="M15 5l-7 7 7 7" />
    </StrokeIcon>
  );
}

export function IconArrowRight({ size = 20, className }: IconProps) {
  return (
    <StrokeIcon size={size} className={className}>
      <path d="M5 12h14M13 6l6 6-6 6" />
    </StrokeIcon>
  );
}

export function IconChevronRight({ size = 20, className }: IconProps) {
  return (
    <StrokeIcon size={size} className={className}>
      <path d="M9 5l7 7-7 7" />
    </StrokeIcon>
  );
}

export function IconClose({ size = 20, className }: IconProps) {
  return (
    <StrokeIcon size={size} className={className}>
      <path d="M6 6l12 12M18 6L6 18" />
    </StrokeIcon>
  );
}

export function IconTrash({ size = 20, className }: IconProps) {
  return (
    <StrokeIcon size={size} className={className}>
      <path d="M4 7h16M9 7V4.8A.8.8 0 0 1 9.8 4h4.4a.8.8 0 0 1 .8.8V7M6.5 7l.8 12.2a1 1 0 0 0 1 .8h7.4a1 1 0 0 0 1-.8L17.5 7" />
      <path d="M10 11v5M14 11v5" />
    </StrokeIcon>
  );
}

export function IconMic({ size = 20, className }: IconProps) {
  return (
    <StrokeIcon size={size} className={className}>
      <rect x="9" y="3" width="6" height="11" rx="3" />
      <path d="M5.5 11.5a6.5 6.5 0 0 0 13 0M12 18v3M9 21h6" />
    </StrokeIcon>
  );
}

export function IconLoop({ size = 20, className }: IconProps) {
  return (
    <StrokeIcon size={size} className={className}>
      <path d="M17 3l3 3-3 3" />
      <path d="M20 6H8.5A4.5 4.5 0 0 0 4 10.5v.5" />
      <path d="M7 21l-3-3 3-3" />
      <path d="M4 18h11.5a4.5 4.5 0 0 0 4.5-4.5V13" />
    </StrokeIcon>
  );
}

export function IconPlus({ size = 20, className }: IconProps) {
  return (
    <StrokeIcon size={size} className={className}>
      <path d="M12 5v14M5 12h14" />
    </StrokeIcon>
  );
}

export function IconSparkle({ size = 20, className }: IconProps) {
  return (
    <StrokeIcon size={size} className={className}>
      <path d="M12 3l1.7 4.8L18.5 9.5l-4.8 1.7L12 16l-1.7-4.8L5.5 9.5l4.8-1.7z" />
      <path d="M18.5 15.5l.8 2.2 2.2.8-2.2.8-.8 2.2-.8-2.2-2.2-.8 2.2-.8z" />
    </StrokeIcon>
  );
}

export function IconKeyboard({ size = 20, className }: IconProps) {
  return (
    <StrokeIcon size={size} className={className}>
      <rect x="2.5" y="6" width="19" height="12" rx="2.2" />
      <path d="M6 10h.01M9.5 10h.01M13 10h.01M16.5 10h.01M8 13.5h8" />
    </StrokeIcon>
  );
}

export function IconSound({ size = 20, className }: IconProps) {
  return (
    <StrokeIcon size={size} className={className}>
      <path d="M11 5.5L6.5 9H3.5v6h3L11 18.5z" />
      <path d="M15 9.5a3.5 3.5 0 0 1 0 5M17.5 7a7 7 0 0 1 0 10" />
    </StrokeIcon>
  );
}

export function IconMusic({ size = 20, className }: IconProps) {
  return (
    <StrokeIcon size={size} className={className}>
      <path d="M9 18V6.4l10-2v11.2" />
      <circle cx="6.5" cy="18" r="2.5" />
      <circle cx="16.5" cy="15.6" r="2.5" />
    </StrokeIcon>
  );
}

export function IconCheck({ size = 20, className }: IconProps) {
  return (
    <StrokeIcon size={size} className={className}>
      <path d="M5 12.5l4.5 4.5L19 6.8" />
    </StrokeIcon>
  );
}

export function IconWarning({ size = 20, className }: IconProps) {
  return (
    <StrokeIcon size={size} className={className}>
      <path d="M12 3.5l9 16H3z" />
      <path d="M12 9v5M12 17h.01" />
    </StrokeIcon>
  );
}

export function IconBookmark({ size = 20, className }: IconProps) {
  return (
    <StrokeIcon size={size} className={className}>
      <path d="M6.5 4h11a1 1 0 0 1 1 1v15.5l-6.5-4-6.5 4V5a1 1 0 0 1 1-1z" />
    </StrokeIcon>
  );
}

export function IconClock({ size = 20, className }: IconProps) {
  return (
    <StrokeIcon size={size} className={className}>
      <circle cx="12" cy="12" r="8.5" />
      <path d="M12 7.5V12l3 2" />
    </StrokeIcon>
  );
}

export function IconRefresh({ size = 20, className }: IconProps) {
  return (
    <StrokeIcon size={size} className={className}>
      <path d="M20 11a8 8 0 1 0-2.3 6.1" />
      <path d="M20 4.5V11h-6.4" />
    </StrokeIcon>
  );
}

export function IconStop({ size = 20, className }: IconProps) {
  return (
    <svg
      viewBox="0 0 24 24"
      width={size}
      height={size}
      className={className}
      aria-hidden
      focusable={false}
    >
      <rect x="7" y="7" width="10" height="10" rx="1.8" fill="currentColor" />
    </svg>
  );
}
