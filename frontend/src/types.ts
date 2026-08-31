export type Direction = "inward" | "outward";
export type ReviewStatus = "unverified" | "needs_review" | "verified";
export type PartyCode = "CTR" | "AE" | "PD" | "UNK";

export interface Letter {
  id: string;
  serial: number;
  letterRef: string;
  dated: string; // YYYY-MM-DD
  received: string | null;
  from: PartyCode;
  to: PartyCode;
  direction: Direction;
  subject: string;
  chainage: string | null; // display form, e.g. "Km 12+400"
  clause: string | null;
  threadKey: string;
  reviewStatus: ReviewStatus;
  repliesToRef: string | null;
  repliesToDated: string | null;
  /** Present only when a field failed extraction and needs a human look. */
  unresolvedField?: string;
  /** A reference this letter cites that the register does not hold. */
  missingCitation?: string;
  /** Present only for live (real-uploaded) letters -- fixture letters have no
   * real source document behind them, so the viewer falls back to its honest
   * placeholder when these are absent. */
  documentSha256?: string;
  pageFrom?: number;
  pageTo?: number;
  /** The uploaded file this letter came from. Present for live letters only;
   * searchable, because "which letter came from this PDF?" is a question people
   * actually ask when reconciling a register against a folder of scans. */
  originalFilename?: string;
}

export type FieldValidation = "exact" | "normalized_exact" | "unresolved";

export interface ExtractedFieldProvenance {
  fieldKey: string;
  fieldIndex: number;
  valueText: string | null;
  valueVerbatim: string | null;
  pageNo: number | null;
  bbox: { union: { x: number; y: number; w: number; h: number } } | null;
  validation: FieldValidation;
}

export interface PackageInfo {
  name: string;
  contractNo: string;
  periodFrom: string;
  periodTo: string;
  documentsIngested: number;
  documentsTotal: number;
}
