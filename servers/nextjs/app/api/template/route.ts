import { NextRequest, NextResponse } from "next/server";
import { promises as fs } from "fs";
import path from "path";

import { compileTemplateSchema } from "@/lib/compile-template-schema";

const DEFAULT_TEMPLATE = "general";

function getTemplatesRoot(): string {
  return path.join(process.cwd(), "app", "presentation-templates");
}

async function readJsonFile<T>(filePath: string, fallback: T): Promise<T> {
  try {
    return JSON.parse(await fs.readFile(filePath, "utf-8")) as T;
  } catch {
    return fallback;
  }
}

function isLayoutSourceFile(fileName: string): boolean {
  return (
    fileName.endsWith(".tsx") &&
    !fileName.startsWith(".") &&
    !fileName.includes(".test.") &&
    !fileName.includes(".spec.") &&
    fileName !== "settings.json"
  );
}

export async function GET(request: NextRequest) {
  const group = request.nextUrl.searchParams.get("group")?.trim() || DEFAULT_TEMPLATE;
  const templateDirectory = path.join(getTemplatesRoot(), group);

  let fileNames: string[];
  try {
    fileNames = await fs.readdir(templateDirectory);
  } catch {
    return NextResponse.json(
      { detail: `Template '${group}' not found` },
      { status: 404 }
    );
  }

  const settings = await readJsonFile(
    path.join(templateDirectory, "settings.json"),
    { description: `${group} presentation layouts`, ordered: false, default: false }
  );

  const layouts = [];
  for (const fileName of fileNames.filter(isLayoutSourceFile)) {
    const source = await fs.readFile(path.join(templateDirectory, fileName), "utf-8");
    const compiled = compileTemplateSchema(source);
    if (!compiled) {
      continue;
    }
    layouts.push({
      id: `${group}:${compiled.layoutId}`,
      name: compiled.layoutName,
      description: compiled.layoutDescription,
      json_schema: compiled.schemaJSON,
    });
  }

  if (!Array.isArray(layouts) || layouts.length === 0) {
    return NextResponse.json(
      { detail: `Template '${group}' not found` },
      { status: 404 }
    );
  }

  return NextResponse.json({
    name: group,
    ordered: Boolean(settings?.ordered),
    slides: layouts,
  });
}
