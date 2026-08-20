import React from "react";
import { Prose } from "@/components/workspace/cards/_shared";
import InlineContent from "@/components/workspace/InlineContent";

export default function AnswerCard({ card }) {
  const hasEmbeds = Array.isArray(card.embeds) && card.embeds.length > 0;
  // NOTE: `card.keyTakeaway` is intentionally NOT shown at the top — it just repeated the
  // answer's opening line. It's kept on the card for future use (e.g. compacting long chats).
  return (
    <div>
      {/* Inline images/charts are in the markdown; rich embeds (files, tables, videos) are
          placed at their [[embed:id]] markers via InlineContent. */}
      {hasEmbeds
        ? <InlineContent summary={card.summary || ""} embeds={card.embeds} />
        : <Prose>{card.summary || ""}</Prose>}
    </div>
  );
}