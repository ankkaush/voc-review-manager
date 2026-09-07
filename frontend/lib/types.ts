export interface Business {
  id: string;
  name: string;
  industry: string;
}

export interface Location {
  id: string;
  business_id: string;
  name: string;
  city: string;
}

export interface Overview {
  business_id: string;
  review_count: number;
  ingestion_status_counts: Record<string, number>;
  analysis_status_counts: Record<string, number>;
  rating_distribution: Record<string, number>;
  sentiment_distribution: Record<string, number>;
  language_distribution: Record<string, number>;
}

export interface AspectSummary {
  topic_key: string;
  topic_label: string;
  aspect_key: string;
  aspect_label: string;
  mention_count: number;
  negative_count: number;
  positive_count: number;
}

export interface AspectsResponse {
  top_negative: AspectSummary[];
  top_positive: AspectSummary[];
}

export interface Issue {
  id: string;
  business_id: string;
  location_id: string | null;
  topic_id: string;
  aspect_id: string;
  title: string;
  description: string;
  status: string;
  severity: string | null;
  priority_score: number | null;
  priority_score_breakdown: Record<string, unknown> | null;
  trend_direction: string | null;
  trend_change_pct: number | null;
  first_detected_at: string;
  last_updated_at: string;
}

export interface MetricEvidenceItem {
  aggregate_period_metric_id: string;
  period_start: string;
  period_end: string;
  mention_count: number;
  negative_count: number;
  positive_count: number;
  neutral_count: number;
  avg_rating: number | null;
  note: string | null;
}

export interface ReviewCitationItem {
  review_id: string;
  text: string;
  rating: number | null;
  submitted_at: string;
}

export interface InsightItem {
  id: string;
  text: string;
  generation_method: string;
  created_at: string;
}

export interface IssueEvidenceResponse {
  issue: Issue;
  metrics: MetricEvidenceItem[];
  review_citations: ReviewCitationItem[];
  latest_insight: InsightItem | null;
}

export interface WorkflowEventItem {
  entity_type: string;
  entity_id: string;
  from_state: string | null;
  to_state: string;
  actor: string;
  reason: string | null;
  created_at: string;
}

export interface Action {
  id: string;
  issue_id: string;
  type: string;
  recommended_text: string;
  status: string;
  assigned_to: string | null;
  created_at: string;
  resolved_at: string | null;
}

export interface Outcome {
  id: string;
  action_id: string;
  before_period_start: string;
  before_period_end: string;
  before_negative_count: number;
  after_period_start: string | null;
  after_period_end: string | null;
  after_negative_count: number | null;
  delta_pct: number | null;
  interpretation: string;
}

export interface Notification {
  id: string;
  business_id: string;
  entity_type: string;
  entity_id: string;
  message: string;
  read: boolean;
  read_at: string | null;
  created_at: string;
}

export interface ProcessingRun {
  id: string;
  trigger: string;
  job_type: string;
  status: string;
  started_at: string | null;
  finished_at: string | null;
  reviews_in_scope: number;
  reviews_succeeded: number;
  reviews_failed: number;
}
