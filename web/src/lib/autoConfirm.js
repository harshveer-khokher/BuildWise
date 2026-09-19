import { confirmModel } from "../api";

/** Auto-confirms every room the parser could not classify with full confidence, instead of
 * blocking on an interactive confirmation screen (removed per user request -- it broke the flow
 * for a demo/presentation). This keeps its existing `use` guess unchanged and just marks it
 * confidence="high" via the same /models/confirm contract the (now-removed) confirmation screen
 * used — no backend change, no different code path, just no human in the loop.
 *
 * Honesty is preserved the same way the plot-size and unresolved-file synthesis already are
 * elsewhere in this app: the uncertainty doesn't vanish, it moves into `assumptions`, which is
 * printed verbatim on the exported report (CLAUDE.md §5) even though there's no on-screen step
 * for it anymore. */
export async function autoConfirmLowConfidenceRooms(model) {
  const toConfirm = [];
  model.floors.forEach((floor) => {
    floor.rooms.forEach((room, roomIndex) => {
      if (room.confidence !== "high") {
        toConfirm.push({ floor_level: floor.level, room_index: roomIndex, use: room.use, confidence: "high" });
      }
    });
  });

  if (toConfirm.length === 0) return model;

  const result = await confirmModel(model, toConfirm);
  const note =
    `${toConfirm.length} room(s) had low/medium-confidence use classification from parsing ` +
    "and were auto-confirmed as-is (no manual review) for this run.";
  return {
    ...result.model,
    assumptions: [...(result.model.assumptions || []), note],
  };
}
