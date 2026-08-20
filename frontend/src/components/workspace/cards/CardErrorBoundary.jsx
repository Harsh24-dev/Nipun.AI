import React from "react";
import { TextFallback } from "@/components/workspace/cards/_shared";

// A bad or unexpected card payload must never take down the whole workspace. This boundary
// catches any render error thrown by a card component and degrades to the shared text fallback
// (title + summary), so the user still sees the answer text instead of a blank/crashed page.
export default class CardErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { failed: false };
  }

  static getDerivedStateFromError() {
    return { failed: true };
  }

  componentDidCatch(error, info) {
    try {
      console.error("Card render failed — falling back to text", error, info);
    } catch {}
  }

  render() {
    if (this.state.failed) {
      return (
        <TextFallback
          card={this.props.card || {}}
          note="This card couldn't be displayed fully — showing the text answer."
        />
      );
    }
    return this.props.children;
  }
}
