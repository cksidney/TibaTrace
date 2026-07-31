import {
  STAGE_STATUS,
  fontSize,
  spacing,
  stageMarker,
  statusPalette,
  surface,
  text,
} from '@dawatrace/shared/design-system/index.js';
import type { StageView } from '@dawatrace/shared/design-system/index.js';

export { stageMarker } from '@dawatrace/shared/design-system/index.js';

/**
 * The nine-stage workflow ribbon.
 *
 * Stage state comes from `deriveStages`, which reads authoritative server
 * state. Visiting a screen never marks a stage complete, and a stage that has
 * not started is not selectable -- a later stage must not become a route around
 * an incomplete earlier one.
 */
export function WorkflowRibbon({
  stages,
  activeStage,
  onSelect,
}: {
  readonly stages: readonly StageView[];
  readonly activeStage?: string;
  readonly onSelect?: (stageId: string) => void;
}) {
  return (
    <nav
      aria-label="Dispensing workflow"
      style={{
        display: 'flex',
        gap: spacing.xs,
        padding: `${spacing.sm}px clamp(${spacing.md}px, 3vw, ${spacing.xl}px)`,
        background: surface.raised,
        borderBottom: `1px solid ${surface.border}`,
        overflowX: 'auto',
      }}
    >
      {stages.map((stage) => {
        const status = STAGE_STATUS[stage.state];
        const palette = statusPalette[status];
        const active = activeStage === stage.id;
        const interactive = stage.navigable && Boolean(onSelect);

        return (
          <button
            key={stage.id}
            type="button"
            disabled={!interactive}
            aria-current={active ? 'step' : undefined}
            // Both the stage state and the reason travel to assistive tech;
            // a blocked stage must say why, not merely look different.
            aria-label={`Step ${stage.step}, ${stage.label}, ${stage.state.replace(/_/g, ' ').toLowerCase()}${
              stage.blockedReason ? `. ${stage.blockedReason}` : ''
            }`}
            title={stage.blockedReason || undefined}
            onClick={interactive ? () => onSelect?.(stage.id) : undefined}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: spacing.sm,
              padding: `${spacing.sm}px ${spacing.md}px`,
              borderRadius: 8,
              border: `1px solid ${active ? palette.accent : surface.border}`,
              background: active ? palette.surface : 'transparent',
              color: stage.state === 'NOT_STARTED' ? text.tertiary : palette.foreground,
              fontSize: fontSize.caption,
              fontWeight: active ? 600 : 500,
              cursor: interactive ? 'pointer' : 'default',
              whiteSpace: 'nowrap',
              flexShrink: 0,
            }}
          >
            <span
              aria-hidden="true"
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                justifyContent: 'center',
                width: 20,
                height: 20,
                borderRadius: 999,
                background: stage.state === 'COMPLETE' ? palette.accent : 'transparent',
                border: `1px solid ${stage.state === 'COMPLETE' ? palette.accent : palette.border}`,
                color: stage.state === 'COMPLETE' ? text.inverse : palette.foreground,
                fontSize: 11,
                fontWeight: 700,
                fontVariantNumeric: 'tabular-nums',
              }}
            >
              {stageMarker(stage.state, stage.step)}
            </span>
            {stage.label}
          </button>
        );
      })}
    </nav>
  );
}
