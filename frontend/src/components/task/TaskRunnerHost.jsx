import React, { useEffect, useState } from "react";
import TaskRunner from "./TaskRunner";

// Mounted once at app root. Any card/button launches a task by dispatching:
//   window.dispatchEvent(new CustomEvent("nipun:start-task", { detail: { goal } }))
// This keeps the launcher decoupled from the chat card that triggers it.
export default function TaskRunnerHost() {
  const [goal, setGoal] = useState(null);

  useEffect(() => {
    const onStart = (e) => setGoal(e.detail?.goal || "");
    window.addEventListener("nipun:start-task", onStart);
    return () => window.removeEventListener("nipun:start-task", onStart);
  }, []);

  if (goal == null) return null;
  return <TaskRunner goal={goal} onClose={() => setGoal(null)} />;
}

export function startTask(goal) {
  window.dispatchEvent(new CustomEvent("nipun:start-task", { detail: { goal } }));
}
