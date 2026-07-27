/** GET /api/v1/drugs 行。 */
export interface DrugSummary {
  drug_id: number;
  brand_name: string;
  generic_name: string | null;
}

export interface Citation {
  brand_name: string;
  section: string;
  excerpt: string;
}

export interface ChatResponse {
  blocked: boolean;
  category: "emergency" | "special_population" | "diagnosis" | "prescription" | null;
  boundary_message: string | null;
  answer: string | null;
  confidence: number | null;
  citations: Citation[];
  sources_note: string | null;
  disclaimer: string | null;
}

export interface MedboxItem {
  drug_id: number;
  brand_name: string;
  dosage_per_day: number | null;
}

export interface MedboxResponse {
  device_id: string;
  items: MedboxItem[];
}

export interface IngredientTotal {
  name: string;
  total_amount_mg: number;
  sources: string[];
  max_daily_mg: number | null;
}

export interface OverlapResult {
  overlapping: IngredientTotal[];
  warnings: string[];
}

export interface TriggeredRule {
  id: string;
  title: string;
  severity: "danger" | "warning" | "info";
  description: string;
  warning: string;
  confidence: "high" | "medium" | "low";
  source: string | null;
}

export interface CheckReport {
  overlap: OverlapResult;
  triggered_rules: TriggeredRule[];
  unresolved_drugs: string[];
}
