import { useState } from "react";
import { confirmModel } from "../api";
import { ConfidenceBadge } from "./StatusBadge";

const ROOM_USES = ["bedroom", "living", "kitchen", "bath", "wc", "store", "stair", "garage", "other"];

/** Model-confirmation screen (CLAUDE.md §5 Confidence semantics).
 *
 * Any room with confidence !== "high" must be reviewed here before checks run — this mirrors
 * the parser's own honest uncertainty instead of quietly guessing on the user's behalf. Only
 * reached when at least one such room exists; otherwise the app skips straight to Analyze.
 */
export default function ConfirmScreen({ model, onConfirmed, onCancel }) {
  const [edits, setEdits] = useState({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const reviewRooms = [];
  model.floors.forEach((floor) => {
    floor.rooms.forEach((room, roomIndex) => {
      if (room.confidence !== "high") {
        reviewRooms.push({ floorLevel: floor.level, roomIndex, room });
      }
    });
  });

  function setUse(key, use) {
    setEdits((prev) => ({ ...prev, [key]: { use } }));
  }

  async function confirmAndContinue() {
    setBusy(true);
    setError(null);
    try {
      const corrections = reviewRooms.map(({ floorLevel, roomIndex, room }) => {
        const key = `${floorLevel}:${roomIndex}`;
        const use = edits[key]?.use ?? room.use;
        return { floor_level: floorLevel, room_index: roomIndex, use, confidence: "high" };
      });
      const result = await confirmModel(model, corrections);
      onConfirmed(result.model);
    } catch (err) {
      setError(String(err.message || err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="screen">
      <div className="screen-header">
        <p className="eyebrow">Before we check your plan</p>
        <h2>Confirm a few room labels</h2>
        <p className="lede">
          The parser could not read these room labels with full confidence. Confirm or correct
          each one — nothing runs against a guess.
        </p>
      </div>

      <div className="table-scroll">
        <table className="data-table">
          <thead>
            <tr>
              <th>Floor</th>
              <th>Parsed as</th>
              <th>Confidence</th>
              <th>Confirm as</th>
            </tr>
          </thead>
          <tbody>
            {reviewRooms.map(({ floorLevel, roomIndex, room }) => {
              const key = `${floorLevel}:${roomIndex}`;
              return (
                <tr key={key}>
                  <td>{floorLevel}</td>
                  <td>{room.use}</td>
                  <td>
                    <ConfidenceBadge confidence={room.confidence} />
                  </td>
                  <td>
                    <select
                      value={edits[key]?.use ?? room.use}
                      onChange={(e) => setUse(key, e.target.value)}
                      aria-label={`Confirm room use for floor ${floorLevel}, room ${roomIndex + 1}`}
                    >
                      {ROOM_USES.map((u) => (
                        <option key={u} value={u}>
                          {u}
                        </option>
                      ))}
                    </select>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <p className="hint">{reviewRooms.length} room(s) need confirmation.</p>

      {error && <p className="error">{error}</p>}

      <div className="actions">
        <button type="button" className="button button--primary" onClick={confirmAndContinue} disabled={busy}>
          {busy ? "Confirming…" : "Confirm & check my plan →"}
        </button>
        <button type="button" className="button button--ghost" onClick={onCancel} disabled={busy}>
          Start over
        </button>
      </div>
    </section>
  );
}
