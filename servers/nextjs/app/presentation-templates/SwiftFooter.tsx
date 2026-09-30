import React from "react";
import { displayWebsite } from "./dummyWebsite";

export function SwiftFooter({ website }: { website?: string }) {
  const url = displayWebsite(website);
  return (
    <>
      <div className="absolute bottom-8 left-12 right-12 flex items-center pointer-events-none">
        {url ? (
          <span
            className="text-[14px] mr-6 shrink-0"
            style={{ color: "var(--background-text, #6B7280)" }}
          >
            {url}
          </span>
        ) : null}
        <div
          className="h-[2px] flex-1"
          style={{ backgroundColor: "var(--background-text, #111827)" }}
        ></div>
      </div>
      <div
        className="absolute bottom-7 right-6 w-8 h-8 rotate-45"
        style={{ backgroundColor: "var(--background-text, #111827)" }}
      ></div>
    </>
  );
}
