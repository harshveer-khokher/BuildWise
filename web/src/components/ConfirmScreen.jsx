import { useState } from "react";
import { confirmModel } from "../api";

const ROOM_USES = ["bedroom", "living", "kitchen", "bath", "wc", "store", "stair", "garage", "other"];

/** Model-confirmation screen (CLAUDE.md §5 Confidence semantics, §10.5 "freeze as truth").
 *
 * confidence === "low" rooms must be user-confirmed before rules run. Wired against
 * s06_low_conf's shape: two rooms come in as confidence="low", one as "medium". This screen
 * lets the user correct the `use` label and confirms every touched room to confidence="high"
 * via POST /models/confirm, matching packages/api/main.py's RoomCorrection contract.
 */
export default function ConfirmScreen({ model, onConfirmed }) {
  const [edits, setEdits] = useState({}); // key: "floorLevel:roomIndex" -> { use }
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const lowOrMediumRooms = [];
  model.floors.forEach((floor) => {
    floor.rooms.forEach((room, roomIndex) => {
      if (room.confidence !== "high") {
        lowOrMediumRooms.push({ floorLevel: floor.level, roomIndex, room });
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
      const corrections = lowOrMediumRooms.map(({ floorLevel, roomIndex, room }) => {
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
      <h2>2. Confirm the parsed model</h2>
      <p className="hint">
        Low-confidence room labels must be confirmed before any rule runs (CLAUDE.md §5) — this
        mirrors the parser's honest uncertainty rather than guessing on your behalf.
      </p>

      <table className="room-table">
        <thead>
          <tr>
            <th>Floor</th>
            <th>Room</th>
            <th>Confidence</th>
            <th>Confirm as</th>
          </tr>
        </thead>
        <tbody>
          {model.floors.flatMap((floor) =>
            floor.rooms.map((room, roomIndex) => {
              const key = `${floor.level}:${roomIndex}`;
              const needsReview = room.confidence !== "high";
              return (
                <tr key={key} className={needsReview ? "row-flagged" : ""}>
                  <td>{floor.level}</td>
                  <td>{room.use}</td>
                  <td className={`confidence-${room.confidence}`}>{room.confidence}</td>
                  <td>
                    {needsReview ? (
                      <select
                        value={edits[key]?.use ?? room.use}
                        onChange={(e) => setUse(key, e.target.value)}
                      >
                        {ROOM_USES.map((u) => (
                          <option key={u} value={u}>
                            {u}
                          </option>
                        ))}
                      </select>
                    ) : (
                      <span className="hint">already confirmed</span>
                    )}
                  </td>
                </tr>
              );
            })
          )}
        </tbody>
      </table>

      {lowOrMediumRooms.length === 0 ? (
        <p className="hint">All rooms are already high-confidence — nothing to confirm.</p>
      ) : (
        <p className="hint">{lowOrMediumRooms.length} room(s) flagged for confirmation.</p>
      )}

      <button onClick={confirmAndContinue} disabled={busy}>
        {busy ? "Confirming…" : "Confirm & run checks"}
      </button>

      {error && <p className="error">{error}</p>}
    </section>
  );
}
