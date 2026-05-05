"use client";

import React, { useMemo, useRef } from "react";
import EditableLayoutWrapper from "../components/EditableLayoutWrapper";
import SlideErrorBoundary from "../components/SlideErrorBoundary";
import TiptapTextReplacer from "../components/TiptapTextReplacer";
import { validate as uuidValidate } from 'uuid';
import { getLayoutByLayoutId } from "@/app/presentation-templates";
import { useCustomTemplateDetails } from "@/app/hooks/useCustomTemplates";
import { updateSlideContent } from "@/store/slices/presentationGeneration";
import { useDispatch } from "react-redux";
import { Loader2 } from "lucide-react";


function toText(value: unknown): string {
    if (typeof value === "string") return value;
    if (value == null) return "";
    return String(value);
}

function collectItems(content: any): { title: string; body: string }[] {
    const source = Array.isArray(content?.bulletPoints)
        ? content.bulletPoints
        : Array.isArray(content?.items)
            ? content.items
            : Array.isArray(content?.metrics)
                ? content.metrics
                : [];

    return source
        .slice(0, 6)
        .map((item: any) => ({
            title: toText(item?.title || item?.label || item?.value || item?.heading),
            body: toText(item?.body || item?.description || item?.text || item?.subtitle),
        }))
        .filter((item: { title: string; body: string }) => item.title || item.body);
}

function findImageUrl(value: any): string {
    if (!value || typeof value !== "object") return "";
    if (typeof value.__image_url__ === "string") return value.__image_url__;
    if (typeof value.url === "string") return value.url;
    if (typeof value.src === "string") return value.src;
    for (const nestedValue of Object.values(value)) {
        const found = findImageUrl(nestedValue);
        if (found) return found;
    }
    return "";
}

function ExportFallbackSlide({ data }: { data: any }) {
    const title = toText(data?.title || data?.heading || "Generated Slide");
    const description = toText(data?.description || data?.body || data?.subtitle);
    const items = collectItems(data);
    const imageUrl = findImageUrl(data);

    return (
        <div className="w-full rounded-sm max-w-[1280px] shadow-lg max-h-[720px] aspect-video bg-white relative z-20 mx-auto overflow-hidden">
            <div className="flex h-full gap-10 p-12">
                <div className="flex-1 flex flex-col justify-center">
                    <h1 className="text-5xl font-bold text-gray-900 leading-tight mb-6">{title}</h1>
                    {description && <p className="text-xl text-gray-700 leading-relaxed mb-8">{description}</p>}
                    {items.length > 0 && (
                        <div className="grid grid-cols-1 gap-4">
                            {items.map((item, index) => (
                                <div key={index} className="rounded-xl border border-gray-200 bg-gray-50 p-4">
                                    {item.title && <div className="text-lg font-semibold text-gray-900">{item.title}</div>}
                                    {item.body && <div className="text-base text-gray-700 mt-1">{item.body}</div>}
                                </div>
                            ))}
                        </div>
                    )}
                </div>
                {imageUrl && (
                    <div className="w-[38%] flex items-center justify-center">
                        <img src={imageUrl} alt={title} className="w-full h-[70%] object-cover rounded-2xl shadow-md" />
                    </div>
                )}
            </div>
        </div>
    );
}



export const V1ContentRender = ({ slide, isEditMode, theme }: { slide: any, isEditMode: boolean, theme?: any, enableEditMode?: boolean }) => {
    const dispatch = useDispatch();
    const containerRef = useRef<HTMLDivElement | null>(null);

    const customTemplateId = slide.layout_group.startsWith("custom-") ? slide.layout_group.split("custom-")[1] : slide.layout_group;
    const isCustomTemplate = uuidValidate(customTemplateId) || slide.layout_group.startsWith("custom-");

    // Always call the hook (React hooks rule), but with empty id when not a custom template
    const { template: customTemplate, loading: customLoading } = useCustomTemplateDetails({
        id: isCustomTemplate ? customTemplateId : "",
        name: isCustomTemplate ? slide.layout_group : "",
        description: ""
    });


    // Memoize layout resolution to prevent unnecessary recalculations
    const Layout = useMemo(() => {
        if (isCustomTemplate) {
            if (customTemplate) {
                const layoutId = slide.layout.startsWith("custom-") ? slide.layout.split(":")[1] : slide.layout;


                const compiledLayout = customTemplate.layouts.find(
                    (layout) => layout.layoutId === layoutId
                );


                return compiledLayout?.component ?? null;
            }
            return null;
        } else {
            const template = getLayoutByLayoutId(slide.layout);
            return template?.component ?? null;
        }
    }, [isCustomTemplate, customTemplate, slide.layout]);

    // Show loading state for custom templates
    if (isCustomTemplate && customLoading) {
        return (
            <div className="flex flex-col items-center justify-center aspect-video h-full bg-gray-100 rounded-lg">
                <Loader2 className="w-4 h-4 animate-spin" />
            </div>
        );
    }


    if (!Layout) {
        if (Object.keys(slide.content).length === 0) {
            return (
                <div className="flex flex-col items-center cursor-pointer justify-center aspect-video h-full bg-gray-100 rounded-lg">
                    <p className="text-gray-600 text-center text-base">Blank Slide</p>
                    <p className="text-gray-600 text-center text-sm">This slide is empty. Please add content to it using the edit button.</p>
                </div>
            )
        }
        return <ExportFallbackSlide data={slide.content} />;
    }
    const LayoutComp = Layout as React.ComponentType<{ data: any }>;

    if (isEditMode) {
        return (
            <SlideErrorBoundary label={`Slide ${slide.index + 1}`}>
                <div ref={containerRef} className={` `}>

                    <EditableLayoutWrapper
                        slideIndex={slide.index}
                        slideData={slide.content}
                        properties={slide.properties}
                    >
                        <TiptapTextReplacer
                            key={slide.id}
                            slideData={slide.content}
                            slideIndex={slide.index}
                            onContentChange={(
                                content: string,
                                dataPath: string,
                                slideIndex?: number
                            ) => {
                                if (dataPath && slideIndex !== undefined) {
                                    dispatch(
                                        updateSlideContent({
                                            slideIndex: slideIndex,
                                            dataPath: dataPath,
                                            content: content,
                                        })
                                    );
                                }
                            }}
                        >
                            <LayoutComp data={{
                                ...slide.content,
                                _logo_url__: theme ? theme.logo_url : null,
                                __companyName__: (theme && theme.company_name) ? theme.company_name : null,
                            }} />
                        </TiptapTextReplacer>
                    </EditableLayoutWrapper>



                </div>
            </SlideErrorBoundary>

        );
    }
    return (
        <LayoutComp data={{
            ...slide.content,
            _logo_url__: theme ? theme.logo_url : null,
            __companyName__: (theme && theme.company_name) ? theme.company_name : null,
        }} />
    )
};

