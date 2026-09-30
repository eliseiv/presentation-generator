import * as z from "zod";

const DUMMY_WEBSITE =
  /yourwebsite\.com|hello\.com|example\.com|lorem|placeholder|localhost/i;

export function displayWebsite(raw?: string | null): string | null {
  const value = (raw || "").trim();
  if (!value || DUMMY_WEBSITE.test(value)) {
    return null;
  }
  return value;
}

export const websiteField = z
  .string()
  .max(60)
  .optional()
  .default("")
  .describe(
    "Real company website only. Leave empty if unknown. Never invent placeholders like www.yourwebsite.com."
  );
