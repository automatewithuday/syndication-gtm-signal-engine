ALTER TABLE unified_account_scores
ADD COLUMN scoring_logic_version TEXT NOT NULL DEFAULT 'unified_scorer_v1';
