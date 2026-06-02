import type { Confidence, DocType, FieldKind, CategoryOption } from "@/schema/types";

export type Status = "queued" | "processing" | "done" | "error";

export type Bbox = [number, number, number, number]; // [x%, y%, w%, h%]

export interface FieldData {
  key: string;
  label: string;
  icon: string;
  kind: FieldKind;
  value: string;
  confidence: Confidence;
  bbox?: Bbox;
  options?: CategoryOption[];
  edited?: boolean;
}

export interface QAEntry {
  question: string;
  answer: string;
  citation?: string;
  thinking?: string;
}

export interface Stage {
  key: string;
  label: string;
  ms: number;
}

export interface DocData {
  id: string;
  filename: string;
  mime: string;
  type: DocType | null;
  status: Status;
  errorMsg?: string;
  isDup?: boolean;
  pageCount: number;
  readMs?: number;
  summary?: string;
  expiresInDays?: number | null;
  fields: FieldData[];
  stages?: Stage[];
  ocrText?: string;
  qa?: QAEntry[];
}
