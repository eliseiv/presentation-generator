import React from "react"
import * as z from "zod"
import { SwiftFooter } from "../SwiftFooter"

const layoutId = "SwiftTableOfContents"
const layoutName = "Table Of Contents"
const layoutDescription = "Swift: Table of contents with up to 10 items (title + description)"

const ToCItemSchema = z
  .object({
    title: z.string().min(3).max(40).default("Introduction"),
    description: z
      .string()
      .min(0)
      .max(60)
      .default("A brief overview of the section."),
  })
  .default({ title: "Introduction", description: "A brief overview of the section." })

const Schema = z
  .object({
    title: z
      .string()
      .min(3)
      .max(60)
      .default("Table of Contents"),
    items: z
      .array(ToCItemSchema)
      .min(1)
      .max(10)
      .default([
        { title: "Introduction", description: "A brief description of our company and goals." },
        { title: "Our Team", description: "Leadership and core contributors." },
        { title: "Timeline", description: "High-level execution plan and milestones." },
        { title: "Recommendations", description: "Key suggestions based on initial requirements." },
        { title: "Solution", description: "What we propose and why it works." },
        { title: "Market", description: "Audience, segments, and opportunity size." },
        { title: "Business Model", description: "How we create and capture value." },
        { title: "Conclusion", description: "Closing notes and next steps." },
        { title: "Business Model", description: "How we create and capture value." },
        { title: "Conclusion", description: "Closing notes and next steps." },
      ]),
    website: z.string().max(60).optional().default(""),
  })
  .default({
    title: "Table of Contents",
    items: [
      { title: "Introduction", description: "A brief description of our company and goals." },
      { title: "Our Team", description: "Leadership and core contributors." },
      { title: "Timeline", description: "High-level execution plan and milestones." },
      { title: "Recommendations", description: "Key suggestions based on initial requirements." },
      { title: "Solution", description: "What we propose and why it works." },
      { title: "Market", description: "Audience, segments, and opportunity size." },
      { title: "Business Model", description: "How we create and capture value." },
      { title: "Conclusion", description: "Closing notes and next steps." },
      { title: "Business Model", description: "How we create and capture value." },
      { title: "Conclusion", description: "Closing notes and next steps." },

    ],
    website: "",
  })

type SlideData = z.infer<typeof Schema>

interface SlideLayoutProps {
  data?: Partial<SlideData>
}

const TableOfContents: React.FC<SlideLayoutProps> = ({ data: slideData }) => {
  const items = slideData?.items || []
  return (
    <>
      <link
        href="https://fonts.googleapis.com/css2?family=Albert+Sans:wght@400;500;600;700&display=swap"
        rel="stylesheet"
      />

      <div
        className=" w-full rounded-sm max-w-[1280px] shadow-lg max-h-[720px] aspect-video relative z-20 mx-auto overflow-hidden"
        style={{
          fontFamily: "var(--heading-font-family,Albert Sans)",
          backgroundColor: "var(--background-color, #FFFFFF)",
        }}
      >
        {/* Header */}
        <div className="px-12 pt-6 pb-2">
          <div className="flex items-center gap-3">
            <div className="w-3 h-3 rotate-45" style={{ backgroundColor: "var(--background-text, #111827)" }}></div>
            <div className="flex items-center gap-1">

              {(slideData as any)?._logo_url__ && <img src={(slideData as any)?._logo_url__} alt="logo" className="w-6 h-6" />}
              {(slideData as any)?.__companyName__ && <span className="text-[16px]" style={{ color: "var(--background-text, #6B7280)" }}>{(slideData as any)?.__companyName__}</span>}
            </div>
          </div>
        </div>

        <div className="px-12 pt-3">
          <h1 className="text-[48px] leading-[1.1] font-semibold" style={{ color: "var(--background-text, #111827)" }}>{slideData?.title}</h1>
        </div>

        {/* List */}
        <div className="px-12 pt-6 pb-28 max-h-[560px] overflow-hidden">
          <div className="grid grid-cols-2 gap-x-12 gap-y-6 max-w-[1180px]">
            {items.slice(0, 10).map((item, idx) => (
              <div key={idx} className="relative">
                <div className="flex items-start gap-6">
                  <div className="flex-none">
                    <div
                      className="leading-none font-semibold"
                      style={{
                        fontSize: 48,
                        color: "var(--primary-color, #BFF4FF)",
                      }}
                    >
                      {String(idx + 1).padStart(2, "0")}
                    </div>
                  </div>
                  <div className="min-w-0 flex-1 pt-1">
                    <div className="text-[22px] leading-[1.2] font-semibold" style={{ color: "var(--background-text, #111827)" }}>
                      {item.title}
                    </div>
                    {item.description && (
                      <div className="mt-2 text-[14px] leading-[1.6]" style={{ color: "var(--background-text, #6B7280)" }}>
                        {item.description}
                      </div>
                    )}
                  </div>
                </div>
                <div className="mt-4 h-px" style={{ backgroundColor: "var(--stroke, #E5E7EB)" }}></div>
              </div>
            ))}
          </div>
        </div>

        {/* Footer (standardized like IntroSlideLayout) */}
        <SwiftFooter website={slideData?.website} />
      </div>
    </>
  )
}

export { Schema, layoutId, layoutName, layoutDescription }
export default TableOfContents


