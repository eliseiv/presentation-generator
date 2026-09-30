const DUMMY_WEBSITE =
  /yourwebsite\.com|hello\.com|example\.com|lorem|placeholder|localhost/i;

export function displayWebsite(raw?: string | null): string | null {
  const value = (raw || "").trim();
  if (!value || DUMMY_WEBSITE.test(value)) {
    return null;
  }
  return value;
}
