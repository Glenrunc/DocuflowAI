// Mirrors shared/schemas.json — the single source of truth for document field schemas.
import schemas from "@shared/schemas.json";

export type Confidence = "high" | "med" | "low";
export type FieldKind = "value" | "category";
export type DocType = "invoice" | "contract" | "medical" | "report" | "id" | "other";

export interface CategoryOption {
  value: string;
  label: string;
  color: string;
}

export interface FieldDef {
  key: string;
  label: string;
  icon: string;
  kind: FieldKind;
  options?: CategoryOption[];
}

export interface TypeDef {
  label: string;
  icon: string;
  pill: { bg: string; fg: string };
  donut: string;
  identifying: string[];
  dynamic: boolean;
  fields: FieldDef[];
}

export interface SchemaDoc {
  version: number;
  groupOrder: DocType[];
  types: Record<DocType, TypeDef>;
  confidenceLevels: Confidence[];
  bboxPalette: string[];
}

export const SCHEMA = schemas as unknown as SchemaDoc;
export const GROUP_ORDER = SCHEMA.groupOrder;
export const BBOX_PALETTE = SCHEMA.bboxPalette;

export const PLACEHOLDER = "—";

export function getType(t: DocType): TypeDef {
  return SCHEMA.types[t];
}

export const CONF_BADGE: Record<Confidence, { bg: string; fg: string; label: string }> = {
  high: { bg: "#D1FAE5", fg: "#065F46", label: "High" },
  med: { bg: "#FEF3C7", fg: "#92400E", label: "Review" },
  low: { bg: "#FEE2E2", fg: "#991B1B", label: "Low" },
};
