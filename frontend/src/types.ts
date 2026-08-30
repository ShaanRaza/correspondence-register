export type Direction = "inward" | "outward";
export type ReviewStatus = "unverified" | "needs_review" | "verified";
export type PartyCode = "CTR" | "AE" | "PD";

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
}

export interface PackageInfo {
  name: string;
  contractNo: string;
  periodFrom: string;
  periodTo: string;
  documentsIngested: number;
  documentsTotal: number;
}
