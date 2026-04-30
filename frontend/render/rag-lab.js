import {
  topKInput,
  candidateKInput,
  ragRerankInput,
  summaryOutput,
  detailOutput,
  ragFlightStageOrder,
  ragFlightStageLabels,
} from "../state.js";
import {
  escapeHtml,
  hasValue,
  firstPresent,
  formatFieldValue,
  formatScoreValue,
  formatSignedScore,
  isPlainObject,
  firstArrayValue,
  firstObjectValue,
  firstDefinedValue,
  firstScalarValue,
  truncateText,
  normalizeStageKey,
} from "./escape.js";
import { renderMetricCards, renderKeyValuePills } from "./common.js";

export function expandRecordList(value, nameKey = "name") {
  if (Array.isArray(value)) {
    return value;
  }
  if (!isPlainObject(value)) {
    return [];
  }
  return Object.entries(value).map(([name, item]) => (
    isPlainObject(item) ? { [nameKey]: name, ...item } : { [nameKey]: name, value: item }
  ));
}

export function looksLikeRagConfigResult(item) {
  if (!isPlainObject(item)) {
    return false;
  }
  return [
    "config",
    "config_name",
    "metrics",
    "summary",
    "aggregate",
    "scores",
    "per_case",
    "cases",
    "case_results",
    "ranking_preview",
    "rankings",
    "previews",
    "failures",
  ].some((key) => Object.prototype.hasOwnProperty.call(item, key));
}

export function normalizeRagConfigResults(data) {
  const resultItems = Array.isArray(data.results) ? data.results : expandRecordList(data.results, "name");
  const rawConfigGroups = [
    expandRecordList(data.config_results, "name"),
    resultItems.some(looksLikeRagConfigResult) ? resultItems : [],
    expandRecordList(data.configs, "name"),
    expandRecordList(data.runs, "name"),
  ];
  const rawConfigs = rawConfigGroups.find((items) => items.length > 0) || [];

  return rawConfigs.map((item, index) => {
    const configItem = isPlainObject(item) ? item : { value: item };
    const configObject = firstObjectValue(configItem.config, configItem.params, configItem.settings);
    const name = firstPresent(
      configItem.name,
      configItem.config_name,
      configItem.id,
      configItem.label,
      configObject.name,
      `config_${index + 1}`,
    );
    return {
      name: formatFieldValue(name),
      metrics: firstObjectValue(configItem.metrics, configItem.summary, configItem.aggregate, configItem.scores),
      cases: firstArrayValue(configItem.per_case, configItem.cases, configItem.case_results),
      rankings: firstArrayValue(configItem.ranking_preview, configItem.rankings, configItem.previews),
      failures: firstArrayValue(configItem.failures, configItem.failure_cases, Array.isArray(configItem.failed_cases) ? configItem.failed_cases : null),
      raw: configItem,
    };
  });
}

export function getRagSummaryMetrics(data, configs) {
  const summary = firstObjectValue(data.summary, data.metrics, data.aggregate, data.scores);
  const entries = Object.entries(summary).filter(([, value]) => (
    !isPlainObject(value) && !Array.isArray(value) && hasValue(value)
  ));
  if (entries.length > 0) {
    return entries;
  }

  return configs.flatMap((config) => (
    Object.entries(config.metrics || {})
      .filter(([, value]) => !isPlainObject(value) && !Array.isArray(value) && hasValue(value))
      .map(([key, value]) => [`${config.name} ${key}`, value])
  ));
}

export function getRagCases(data, configs) {
  const directCases = firstArrayValue(
    data.per_case,
    data.cases,
    data.case_results,
    Array.isArray(data.results) && !data.results.some(looksLikeRagConfigResult) ? data.results : null,
  );
  if (directCases.length > 0) {
    return directCases;
  }
  return configs.flatMap((config) => (
    (config.cases || []).map((item) => (
      isPlainObject(item) ? { config_name: config.name, ...item } : { config_name: config.name, value: item }
    ))
  ));
}

export function getRagRankingPreviews(data, cases, configs) {
  const directRankings = firstArrayValue(data.ranking_preview, data.rankings, data.previews);
  if (directRankings.length > 0) {
    return directRankings;
  }
  if (isPlainObject(data.ranking_preview) || isPlainObject(data.rerank_preview)) {
    return expandRecordList(data.ranking_preview || data.rerank_preview, "case_id");
  }

  const caseRankings = cases
    .filter((item) => isPlainObject(item) && (
      item.ranking_preview || item.rankings || item.before || item.after || item.pre_rerank || item.post_rerank || item.rerank_on || item.rerank_off
    ))
    .map((item) => ({ case_id: firstPresent(item.case_id, item.id), ...firstObjectValue(item.ranking_preview, item.rankings, item) }));
  if (caseRankings.length > 0) {
    return caseRankings;
  }

  return configs.flatMap((config) => (
    (config.rankings || []).map((item) => ({ config_name: config.name, ...item }))
  ));
}

export function getRagFailures(data, cases, configs) {
  const directFailures = firstArrayValue(
    data.failures,
    data.failure_cases,
    Array.isArray(data.failed_cases) ? data.failed_cases : null,
  );
  if (directFailures.length > 0) {
    return directFailures;
  }

  const configFailures = configs.flatMap((config) => (
    (config.failures || []).map((item) => (
      isPlainObject(item) ? { config_name: config.name, ...item } : { config_name: config.name, reason: item }
    ))
  ));
  if (configFailures.length > 0) {
    return configFailures;
  }

  return cases.filter((item) => isPlainObject(item) && (
    item.failed === true || item.passed === false || item.pass === false || item.ok === false
  ));
}

export function renderRagConfigStrip(data, configs) {
  const requestConfig = firstObjectValue(data.request, data.config, data.params);
  const topK = firstPresent(requestConfig.top_k, topKInput?.value);
  const candidateK = firstPresent(requestConfig.candidate_k, candidateKInput?.value);
  const rerank = firstPresent(requestConfig.use_rerank, requestConfig.rerank, ragRerankInput ? String(ragRerankInput.checked) : "");
  const configNames = configs.map((config) => config.name).filter(Boolean);
  return `
    <div class="config-strip">
      ${hasValue(topK) ? `<span class="config-chip">top_k ${escapeHtml(formatFieldValue(topK))}</span>` : ""}
      ${hasValue(candidateK) ? `<span class="config-chip">candidate_k ${escapeHtml(formatFieldValue(candidateK))}</span>` : ""}
      ${hasValue(rerank) ? `<span class="config-chip">rerank ${escapeHtml(formatFieldValue(rerank))}</span>` : ""}
      ${configNames.map((name) => `<span class="config-chip">${escapeHtml(name)}</span>`).join("")}
    </div>
  `;
}

export function renderRagCaseCards(cases) {
  if (!cases || cases.length === 0) {
    return `<div class="detail-block"><h4>Per-case</h4><p class="block-note">\u540E\u7AEF\u8FD8\u6CA1\u6709\u8FD4\u56DE\u9010\u9898\u7ED3\u679C\u3002</p></div>`;
  }
  return `
    <div class="detail-block">
      <h4>Per-case</h4>
      <div class="rag-case-grid">
        ${cases.map((item, index) => {
          const caseItem = isPlainObject(item) ? item : { value: item };
          const caseId = firstPresent(caseItem.case_id, caseItem.id, caseItem.name, `case_${index + 1}`);
          const question = firstPresent(caseItem.question, caseItem.query, caseItem.input);
          const answer = firstPresent(caseItem.answer, caseItem.response, caseItem.output, caseItem.value);
          const configBlocks = isPlainObject(caseItem.configs)
            ? Object.entries(caseItem.configs).map(([name, value]) => `
              <div class="rag-config-result">
                <strong>${escapeHtml(name)}</strong>
                ${renderKeyValuePills(value, ["answer", "response", "ranking_preview", "rankings", "evidence"])}
              </div>
            `).join("")
            : "";
          return `
            <article class="rag-case-card">
              <header>
                <div>
                  <strong>${escapeHtml(caseId)}</strong>
                  ${hasValue(question) ? `<p class="block-note">${escapeHtml(formatFieldValue(question))}</p>` : ""}
                </div>
              </header>
              ${renderKeyValuePills(caseItem, [
                "case_id",
                "id",
                "name",
                "question",
                "query",
                "input",
                "answer",
                "response",
                "output",
                "configs",
                "ranking_preview",
                "rankings",
                "evidence",
                "trace",
                "value",
              ])}
              ${configBlocks}
              ${hasValue(answer) ? `<p class="rag-answer-preview">${escapeHtml(formatFieldValue(answer))}</p>` : ""}
            </article>
          `;
        }).join("")}
      </div>
    </div>
  `;
}

export function renderRankingList(title, items) {
  if (!Array.isArray(items) || items.length === 0) {
    return "";
  }
  return `
    <div class="ranking-column">
      <h5>${escapeHtml(title)}</h5>
      <ol class="ranking-list">
        ${items.slice(0, 8).map((item, index) => {
          const rank = isPlainObject(item) ? firstPresent(item.rank, item.position, index + 1) : index + 1;
          const titleText = isPlainObject(item)
            ? firstPresent(item.title, item.paper_id, item.document_id, item.doc_id, item.id, item.text, item.snippet, "\u672A\u547D\u540D\u7ED3\u679C")
            : item;
          const score = isPlainObject(item) ? formatScoreValue(firstPresent(item.score, item.relevance_score, item.similarity)) : "";
          return `
            <li>
              <span>${escapeHtml(rank)}</span>
              <strong>${escapeHtml(formatFieldValue(titleText))}</strong>
              ${score ? `<em>${escapeHtml(score)}</em>` : ""}
            </li>
          `;
        }).join("")}
      </ol>
    </div>
  `;
}

export function renderRagRankingPreviews(previews) {
  if (!previews || previews.length === 0) {
    return `<div class="detail-block"><h4>Ranking preview</h4><p class="block-note">\u540E\u7AEF\u8FD8\u6CA1\u6709\u8FD4\u56DE\u6392\u5E8F\u9884\u89C8\u3002</p></div>`;
  }

  return `
    <div class="detail-block">
      <h4>Ranking preview</h4>
      <div class="ranking-preview-grid">
        ${previews.slice(0, 6).map((preview, index) => {
          const previewObject = isPlainObject(preview) ? preview : { value: preview };
          const caseId = firstPresent(previewObject.case_id, previewObject.id, previewObject.question, `preview_${index + 1}`);
          const configName = firstPresent(previewObject.config_name, previewObject.name);
          const configuredColumns = isPlainObject(previewObject.configs)
            ? Object.entries(previewObject.configs).map(([name, value]) => renderRankingList(name, value))
            : [];
          const columns = [
            renderRankingList("Before", firstArrayValue(previewObject.before, previewObject.pre_rerank, previewObject.candidates)),
            renderRankingList("After", firstArrayValue(previewObject.after, previewObject.post_rerank, previewObject.reranked)),
            renderRankingList("rerank_on", firstArrayValue(previewObject.rerank_on)),
            renderRankingList("rerank_off", firstArrayValue(previewObject.rerank_off)),
            ...configuredColumns,
          ].filter(Boolean);
          return `
            <article class="ranking-preview">
              <header>
                <strong>${escapeHtml(formatFieldValue(caseId))}</strong>
                ${hasValue(configName) ? `<span class="config-chip">${escapeHtml(formatFieldValue(configName))}</span>` : ""}
              </header>
              ${columns.length ? `<div class="ranking-columns">${columns.join("")}</div>` : renderKeyValuePills(previewObject, ["case_id", "id", "question", "config_name", "name"])}
            </article>
          `;
        }).join("")}
      </div>
    </div>
  `;
}

export function getRagDiagnosticRecordList(value, nameKey = "case_id") {
  if (Array.isArray(value)) {
    return value;
  }
  if (!isPlainObject(value)) {
    return hasValue(value) ? [{ [nameKey]: "all", value }] : [];
  }

  const directItems = firstArrayValue(value.items, value.records, value.entries, value.per_case, value.cases, value.results);
  if (directItems.length > 0) {
    return directItems;
  }
  if (looksLikeFlightRecorder(value) || looksLikeCourtroomRecord(value) || getFailureReasonValue(value) !== undefined) {
    return [value];
  }
  return expandRecordList(value, nameKey);
}

export function looksLikeFlightRecorder(value) {
  if (!isPlainObject(value)) {
    return Array.isArray(value);
  }
  if (Array.isArray(value.value) || looksLikeFlightRecorder(value.value)) {
    return true;
  }
  return [
    "flight_recorder",
    "flight",
    "stages",
    "timeline",
    "pipeline",
    "steps",
    "events",
    ...ragFlightStageOrder,
  ].some((key) => Object.prototype.hasOwnProperty.call(value, key));
}

export function getFlightRecorderValue(item) {
  if (!isPlainObject(item)) {
    return undefined;
  }
  return firstDefinedValue(
    item.flight_recorder,
    item.flight,
    item.pipeline_timeline,
    item.timeline,
    item.pipeline,
    item.stages,
  );
}

export function normalizeFlightStageContainer(value) {
  if (Array.isArray(value)) {
    return value;
  }
  if (isPlainObject(value)) {
    return Object.entries(value).map(([stage, item]) => {
      if (isPlainObject(item)) {
        return { stage, ...item };
      }
      if (Array.isArray(item)) {
        return { stage, items: item };
      }
      return { stage, value: item };
    });
  }
  return [];
}

export function getFlightStageItems(record) {
  const recordObject = isPlainObject(record) ? record : { stages: record };
  const container = firstDefinedValue(
    recordObject.stages,
    recordObject.timeline,
    recordObject.pipeline,
    recordObject.steps,
    recordObject.events,
    recordObject.value,
  );
  const directStages = normalizeFlightStageContainer(container);
  if (directStages.length > 0) {
    return directStages;
  }

  return Object.entries(recordObject)
    .filter(([key]) => ragFlightStageOrder.includes(normalizeStageKey(key)))
    .map(([stage, value]) => {
      if (isPlainObject(value)) {
        return { stage, ...value };
      }
      if (Array.isArray(value)) {
        return { stage, items: value };
      }
      return { stage, value };
    });
}

export function normalizeFlightTopItem(item, index, fallback = {}) {
  const itemObject = isPlainObject(item) ? item : { id: item };
  return {
    rank: firstScalarValue(itemObject.rank, itemObject.position, fallback.rank, index + 1),
    id: firstPresent(
      itemObject.paper_id,
      itemObject.document_id,
      itemObject.doc_id,
      itemObject.chunk_id,
      itemObject.source_id,
      itemObject.id,
      itemObject.title,
      itemObject.value,
      fallback.id,
    ),
    section: firstPresent(
      itemObject.section,
      itemObject.section_label,
      itemObject.section_id,
      itemObject.chunk_section,
      itemObject.source_section,
      fallback.section,
    ),
    score: formatScoreValue(firstPresent(itemObject.score, itemObject.relevance_score, itemObject.similarity, fallback.score)),
  };
}

export function getFlightTopItems(stage) {
  const stageObject = isPlainObject(stage) ? stage : { value: stage };
  const collection = firstArrayValue(
    stageObject.top,
    stageObject.top_items,
    stageObject.top_results,
    stageObject.results,
    stageObject.candidates,
    stageObject.documents,
    stageObject.docs,
    stageObject.chunks,
    stageObject.items,
    stageObject.value,
  );
  if (collection.length > 0) {
    return collection.map((item, index) => normalizeFlightTopItem(item, index));
  }

  if (isPlainObject(stageObject.value)) {
    return getFlightTopItems(stageObject.value);
  }

  const ids = firstArrayValue(
    stageObject.top_ids,
    stageObject.ids,
    stageObject.paper_ids,
    stageObject.document_ids,
    stageObject.doc_ids,
    stageObject.chunk_ids,
  );
  const sections = firstArrayValue(stageObject.top_sections, stageObject.sections, stageObject.section_ids, stageObject.section_labels);
  const scores = firstArrayValue(stageObject.scores, stageObject.top_scores);
  const rowCount = Math.max(ids.length, sections.length, scores.length);
  return Array.from({ length: rowCount }).map((_, index) => normalizeFlightTopItem(
    {},
    index,
    { id: ids[index], section: sections[index], score: scores[index] },
  ));
}

export function normalizeFlightStage(stage, index) {
  const stageObject = isPlainObject(stage) ? stage : { value: stage };
  const stageName = firstPresent(stageObject.stage, stageObject.name, stageObject.label, stageObject.type, `stage_${index + 1}`);
  const normalizedName = normalizeStageKey(stageName);
  const note = firstScalarValue(
    stageObject.expanded_query,
    stageObject.query,
    stageObject.message,
    stageObject.note,
    stageObject.description,
    Array.isArray(stageObject.value) || isPlainObject(stageObject.value) ? "" : stageObject.value,
  );
  return {
    name: normalizedName,
    label: ragFlightStageLabels[normalizedName] || formatFieldValue(stageName),
    order: ragFlightStageOrder.includes(normalizedName) ? ragFlightStageOrder.indexOf(normalizedName) : ragFlightStageOrder.length + index,
    topItems: getFlightTopItems(stageObject),
    note,
  };
}

export function normalizeFlightRecord(item, index, defaults = {}) {
  const itemObject = isPlainObject(item) ? item : { stages: item };
  const nestedValue = getFlightRecorderValue(itemObject);
  const sourceObject = nestedValue !== undefined && nestedValue !== itemObject
    ? (isPlainObject(nestedValue) ? { ...itemObject, ...nestedValue } : { ...itemObject, stages: nestedValue })
    : itemObject;
  const stages = getFlightStageItems(sourceObject)
    .map((stage, stageIndex) => normalizeFlightStage(stage, stageIndex))
    .filter((stage) => stage.label || stage.topItems.length > 0 || hasValue(stage.note))
    .sort((left, right) => left.order - right.order);

  return {
    caseId: firstPresent(sourceObject.case_id, sourceObject.id, sourceObject.name, defaults.caseId, `case_${index + 1}`),
    configName: firstPresent(sourceObject.config_name, sourceObject.config, sourceObject.run, defaults.configName),
    question: firstPresent(sourceObject.question, sourceObject.query, sourceObject.input, defaults.question),
    stages,
  };
}

export function getRagFlightRecorders(data, cases, configs) {
  const records = [];

  [
    data.flight_recorder,
    data.flight_recorders,
    data.flight,
    data.pipeline_timeline,
  ].forEach((source) => {
    getRagDiagnosticRecordList(source, "case_id").forEach((item) => {
      if (looksLikeFlightRecorder(item)) {
        records.push(normalizeFlightRecord(item, records.length));
      }
    });
  });

  cases.forEach((item, index) => {
    if (!isPlainObject(item)) {
      return;
    }
    const defaults = {
      caseId: firstPresent(item.case_id, item.id, item.name, `case_${index + 1}`),
      configName: firstPresent(item.config_name, item.config, item.run),
      question: firstPresent(item.question, item.query, item.input),
    };
    const directValue = getFlightRecorderValue(item);
    if (directValue !== undefined) {
      records.push(normalizeFlightRecord({ ...item, flight_recorder: directValue }, records.length, defaults));
    }
    if (isPlainObject(item.configs)) {
      Object.entries(item.configs).forEach(([configName, configValue]) => {
        if (looksLikeFlightRecorder(configValue)) {
          records.push(normalizeFlightRecord(configValue, records.length, { ...defaults, configName }));
        }
      });
    }
  });

  configs.forEach((config) => {
    [
      config.raw?.flight_recorder,
      config.raw?.flight_recorders,
      config.raw?.flight,
      config.raw?.pipeline_timeline,
    ].forEach((source) => {
      getRagDiagnosticRecordList(source, "case_id").forEach((item) => {
        if (looksLikeFlightRecorder(item)) {
          records.push(normalizeFlightRecord(item, records.length, { configName: config.name }));
        }
      });
    });
  });

  const seen = new Set();
  return records.filter((record) => {
    if (record.stages.length === 0) {
      return false;
    }
    const key = `${record.caseId}|${record.configName}|${record.stages.map((stage) => stage.name).join(",")}`;
    if (seen.has(key)) {
      return false;
    }
    seen.add(key);
    return true;
  });
}

export function renderFlightStageTopItems(stage) {
  if (!stage.topItems || stage.topItems.length === 0) {
    return hasValue(stage.note)
      ? `<p class="flight-note">${escapeHtml(truncateText(stage.note, 140))}</p>`
      : `<p class="flight-note">\u6CA1\u6709\u8FD4\u56DE top ids\u3002</p>`;
  }
  return `
    <ol class="flight-top-list">
      ${stage.topItems.slice(0, 5).map((item, index) => {
        const resultId = firstPresent(item.id, `result_${index + 1}`);
        return `
          <li>
            <span>${escapeHtml(formatFieldValue(item.rank || index + 1))}</span>
            <strong>${escapeHtml(truncateText(resultId, 46))}</strong>
            ${hasValue(item.section) ? `<em>${escapeHtml(truncateText(item.section, 36))}</em>` : ""}
            ${item.score ? `<small>${escapeHtml(item.score)}</small>` : ""}
          </li>
        `;
      }).join("")}
    </ol>
  `;
}

export function renderRagFlightRecorder(records) {
  if (!records || records.length === 0) {
    return `
      <div class="detail-block rag-debug-block">
        <h4>Flight Recorder</h4>
        <p class="block-note">\u540E\u7AEF\u8FD8\u6CA1\u6709\u8FD4\u56DE flight_recorder\uFF1B\u6682\u65F6\u53EA\u80FD\u770B\u4E0B\u65B9\u9010\u9898\u548C\u6392\u5E8F\u9884\u89C8\u3002</p>
      </div>
    `;
  }

  return `
    <div class="detail-block rag-debug-block">
      <h4>Flight Recorder</h4>
      <div class="flight-grid">
        ${records.slice(0, 8).map((record) => `
          <article class="flight-record">
            <header>
              <div>
                <strong>${escapeHtml(formatFieldValue(record.caseId))}</strong>
                ${hasValue(record.question) ? `<p class="block-note">${escapeHtml(truncateText(record.question, 120))}</p>` : ""}
              </div>
              ${hasValue(record.configName) ? `<span class="config-chip">${escapeHtml(formatFieldValue(record.configName))}</span>` : ""}
            </header>
            <ol class="flight-timeline">
              ${record.stages.map((stage, index) => `
                <li class="flight-stage">
                  <div class="flight-stage-head">
                    <span>${escapeHtml(index + 1)}</span>
                    <strong>${escapeHtml(stage.label)}</strong>
                  </div>
                  ${renderFlightStageTopItems(stage)}
                </li>
              `).join("")}
            </ol>
          </article>
        `).join("")}
      </div>
    </div>
  `;
}

export function looksLikeCourtroomRecord(value) {
  if (!isPlainObject(value)) {
    return false;
  }
  return [
    "courtroom",
    "rerank_courtroom",
    "verdict",
    "outcome",
    "before_rank",
    "after_rank",
    "mrr_delta",
    "coverage_delta",
  ].some((key) => Object.prototype.hasOwnProperty.call(value, key));
}

export function getCourtroomValue(item) {
  if (!isPlainObject(item)) {
    return undefined;
  }
  return firstDefinedValue(
    item.courtroom,
    item.rerank_courtroom,
    item.rerank_court,
    item.rerank_judgement,
    item.rerank_judgment,
    item.judgement,
    item.judgment,
  );
}

export function normalizeCourtroomRecord(item, index, defaults = {}) {
  const itemObject = isPlainObject(item) ? item : { reason: item };
  const nestedValue = getCourtroomValue(itemObject);
  const sourceObject = isPlainObject(nestedValue) ? { ...itemObject, ...nestedValue } : itemObject;
  return {
    caseId: firstPresent(sourceObject.case_id, sourceObject.id, sourceObject.name, defaults.caseId, `case_${index + 1}`),
    configName: firstPresent(sourceObject.config_name, sourceObject.config, sourceObject.run, defaults.configName),
    verdict: normalizeStageKey(firstScalarValue(sourceObject.verdict, sourceObject.outcome, sourceObject.status, sourceObject.result, "unavailable")),
    beforeRank: firstScalarValue(sourceObject.before_rank, sourceObject.rank_before, sourceObject.pre_rank, sourceObject.original_rank),
    afterRank: firstScalarValue(sourceObject.after_rank, sourceObject.rank_after, sourceObject.post_rank, sourceObject.reranked_rank),
    mrrDelta: firstScalarValue(sourceObject.mrr_delta, sourceObject.delta_mrr, sourceObject.mrr_change),
    coverageDelta: firstScalarValue(sourceObject.coverage_delta, sourceObject.delta_coverage, sourceObject.keyword_coverage_delta),
    reason: firstScalarValue(sourceObject.reason, sourceObject.explanation, sourceObject.message, sourceObject.error),
  };
}

export function getRagCourtroom(data, cases, configs) {
  const rows = [];

  [
    data.courtroom,
    data.rerank_courtroom,
    data.rerank_court,
    data.rerank_judgement,
    data.rerank_judgment,
  ].forEach((source) => {
    getRagDiagnosticRecordList(source, "case_id").forEach((item) => {
      if (looksLikeCourtroomRecord(item)) {
        rows.push(normalizeCourtroomRecord(item, rows.length));
      }
    });
  });

  cases.forEach((item, index) => {
    if (!isPlainObject(item)) {
      return;
    }
    const defaults = {
      caseId: firstPresent(item.case_id, item.id, item.name, `case_${index + 1}`),
      configName: firstPresent(item.config_name, item.config, item.run),
    };
    const directValue = getCourtroomValue(item);
    if (directValue !== undefined || looksLikeCourtroomRecord(item)) {
      rows.push(normalizeCourtroomRecord({ ...item, courtroom: directValue }, rows.length, defaults));
    }
    if (isPlainObject(item.configs)) {
      Object.entries(item.configs).forEach(([configName, configValue]) => {
        if (looksLikeCourtroomRecord(configValue)) {
          rows.push(normalizeCourtroomRecord(configValue, rows.length, { ...defaults, configName }));
        }
      });
    }
  });

  configs.forEach((config) => {
    [
      config.raw?.courtroom,
      config.raw?.rerank_courtroom,
      config.raw?.rerank_court,
    ].forEach((source) => {
      getRagDiagnosticRecordList(source, "case_id").forEach((item) => {
        if (looksLikeCourtroomRecord(item)) {
          rows.push(normalizeCourtroomRecord(item, rows.length, { configName: config.name }));
        }
      });
    });
  });

  const seen = new Set();
  return rows.filter((row) => {
    const hasDiagnostic = ["helped", "hurt", "no_op", "failed", "unavailable"].includes(row.verdict)
      || hasValue(row.beforeRank)
      || hasValue(row.afterRank)
      || hasValue(row.reason);
    if (!hasDiagnostic) {
      return false;
    }
    const key = `${row.caseId}|${row.configName}|${row.verdict}|${row.beforeRank}|${row.afterRank}`;
    if (seen.has(key)) {
      return false;
    }
    seen.add(key);
    return true;
  });
}

export function renderRankShift(beforeRank, afterRank) {
  const beforeText = hasValue(beforeRank) ? formatFieldValue(beforeRank) : "n/a";
  const afterText = hasValue(afterRank) ? formatFieldValue(afterRank) : "n/a";
  return `${beforeText} -> ${afterText}`;
}

export function renderRagCourtroom(rows) {
  if (!rows || rows.length === 0) {
    return `
      <div class="detail-block rag-debug-block">
        <h4>Rerank Courtroom</h4>
        <p class="block-note">\u540E\u7AEF\u8FD8\u6CA1\u6709\u8FD4\u56DE courtroom\uFF1Brerank \u5224\u51B3\u4F1A\u5728\u8FD9\u91CC\u663E\u793A helped / hurt / no_op\u3002</p>
      </div>
    `;
  }

  return `
    <div class="detail-block rag-debug-block courtroom-block">
      <h4>Rerank Courtroom</h4>
      <div class="courtroom-table-wrap">
        <table class="courtroom-table">
          <thead>
            <tr>
              <th>case</th>
              <th>config</th>
              <th>verdict</th>
              <th>rank</th>
              <th>mrr</th>
              <th>coverage</th>
              <th>reason</th>
            </tr>
          </thead>
          <tbody>
            ${rows.slice(0, 12).map((row) => `
              <tr>
                <td>${escapeHtml(truncateText(row.caseId, 34))}</td>
                <td>${hasValue(row.configName) ? escapeHtml(truncateText(row.configName, 28)) : "n/a"}</td>
                <td><span class="verdict-chip verdict-${escapeHtml(row.verdict)}">${escapeHtml(row.verdict)}</span></td>
                <td>${escapeHtml(renderRankShift(row.beforeRank, row.afterRank))}</td>
                <td>${escapeHtml(formatSignedScore(row.mrrDelta) || "n/a")}</td>
                <td>${escapeHtml(formatSignedScore(row.coverageDelta) || "n/a")}</td>
                <td>${hasValue(row.reason) ? escapeHtml(truncateText(row.reason, 120)) : "n/a"}</td>
              </tr>
            `).join("")}
          </tbody>
        </table>
      </div>
    </div>
  `;
}

export function getFailureReasonValue(item) {
  if (!isPlainObject(item)) {
    return item;
  }
  return firstDefinedValue(
    item.failure_reasons,
    item.failure_reason,
    item.reason_codes,
    item.failure_tags,
    item.tags,
    item.causes,
    item.reasons,
  );
}

export function normalizeFailureReasonList(value) {
  if (value === undefined || value === null) {
    return [];
  }
  if (Array.isArray(value)) {
    return value.flatMap((item) => normalizeFailureReasonList(item));
  }
  if (isPlainObject(value)) {
    const nested = getFailureReasonValue(value);
    if (nested !== value && nested !== undefined) {
      return normalizeFailureReasonList(nested);
    }
    const directCode = firstScalarValue(value.reason, value.code, value.type, value.name, value.label, value.cause);
    if (directCode) {
      return [{
        code: normalizeStageKey(directCode),
        count: firstScalarValue(value.count, value.total, value.value),
        detail: firstScalarValue(value.detail, value.message, value.note, value.description),
      }];
    }
    return Object.entries(value)
      .filter(([key, itemValue]) => (
        hasValue(key)
        && itemValue !== false
        && itemValue !== 0
        && itemValue !== null
        && itemValue !== undefined
      ))
      .map(([key, itemValue]) => ({
        code: normalizeStageKey(key),
        count: typeof itemValue === "number" ? itemValue : "",
        detail: isPlainObject(itemValue) ? firstScalarValue(itemValue.detail, itemValue.message, itemValue.note) : "",
      }));
  }
  return formatFieldValue(value)
    .split(/[,;|]/)
    .map((item) => normalizeStageKey(item))
    .filter(Boolean)
    .map((code) => ({ code, count: "", detail: "" }));
}

export function normalizeFailureLensEntry(item, index, defaults = {}) {
  const itemObject = isPlainObject(item) ? item : { failure_reasons: item };
  const rawReasons = getFailureReasonValue(itemObject);
  let reasons = normalizeFailureReasonList(rawReasons);
  const verdict = normalizeStageKey(firstScalarValue(itemObject.verdict, itemObject.outcome));
  if (reasons.length === 0 && verdict === "hurt") {
    reasons = [{ code: "rerank_hurt", count: "", detail: "" }];
  }
  const seenReasons = new Set();
  reasons = reasons.filter((reason) => {
    if (!reason.code || seenReasons.has(reason.code)) {
      return false;
    }
    seenReasons.add(reason.code);
    return true;
  });
  return {
    caseId: firstPresent(itemObject.case_id, itemObject.id, itemObject.name, defaults.caseId, `case_${index + 1}`),
    configName: firstPresent(itemObject.config_name, itemObject.config, itemObject.run, defaults.configName),
    reasons,
    note: firstScalarValue(itemObject.reason, itemObject.message, itemObject.note, itemObject.error),
  };
}

export function appendFailureLensSource(entries, source, defaults = {}) {
  if (source === undefined || source === null) {
    return;
  }
  if (Array.isArray(source)) {
    if (source.every((item) => !isPlainObject(item))) {
      entries.push(normalizeFailureLensEntry({ failure_reasons: source }, entries.length, defaults));
      return;
    }
    source.forEach((item) => entries.push(normalizeFailureLensEntry(item, entries.length, defaults)));
    return;
  }
  if (isPlainObject(source)) {
    const directItems = firstArrayValue(source.items, source.records, source.entries, source.per_case, source.cases, source.results);
    if (directItems.length > 0) {
      directItems.forEach((item) => entries.push(normalizeFailureLensEntry(item, entries.length, defaults)));
      return;
    }
    if (getFailureReasonValue(source) !== undefined || firstScalarValue(source.reason, source.verdict, source.outcome)) {
      entries.push(normalizeFailureLensEntry(source, entries.length, defaults));
      return;
    }
    Object.entries(source).forEach(([caseId, value]) => {
      entries.push(normalizeFailureLensEntry(value, entries.length, { ...defaults, caseId }));
    });
    return;
  }
  entries.push(normalizeFailureLensEntry(source, entries.length, defaults));
}

export function getRagFailureLens(data, cases, failures, configs, courtroomRows) {
  const entries = [];
  appendFailureLensSource(entries, data.failure_reasons);
  appendFailureLensSource(entries, data.failure_reason);
  appendFailureLensSource(entries, data.failure_lens);

  cases.forEach((item, index) => {
    if (!isPlainObject(item)) {
      return;
    }
    const defaults = {
      caseId: firstPresent(item.case_id, item.id, item.name, `case_${index + 1}`),
      configName: firstPresent(item.config_name, item.config, item.run),
    };
    const reasonValue = getFailureReasonValue(item);
    if (reasonValue !== undefined) {
      entries.push(normalizeFailureLensEntry(item, entries.length, defaults));
    }
    if (isPlainObject(item.configs)) {
      Object.entries(item.configs).forEach(([configName, configValue]) => {
        if (getFailureReasonValue(configValue) !== undefined) {
          entries.push(normalizeFailureLensEntry(configValue, entries.length, { ...defaults, configName }));
        }
      });
    }
  });

  failures.forEach((item, index) => {
    entries.push(normalizeFailureLensEntry(item, entries.length, {
      caseId: isPlainObject(item) ? firstPresent(item.case_id, item.id, item.name, `failure_${index + 1}`) : `failure_${index + 1}`,
      configName: isPlainObject(item) ? firstPresent(item.config_name, item.config, item.run) : "",
    }));
  });

  configs.forEach((config) => {
    [config.raw?.failure_reasons, config.raw?.failure_reason, config.raw?.failure_lens].forEach((source) => {
      appendFailureLensSource(entries, source, { configName: config.name });
    });
  });

  courtroomRows.forEach((row) => {
    if (row.verdict === "hurt") {
      entries.push(normalizeFailureLensEntry(
        { failure_reasons: ["rerank_hurt"], reason: row.reason },
        entries.length,
        { caseId: row.caseId, configName: row.configName },
      ));
    }
  });

  const seen = new Set();
  return entries
    .filter((entry) => entry.reasons.length > 0)
    .filter((entry) => {
      const key = `${entry.caseId}|${entry.configName}|${entry.reasons.map((reason) => reason.code).join(",")}`;
      if (seen.has(key)) {
        return false;
      }
      seen.add(key);
      return true;
    });
}

export function getFailureReasonClass(code) {
  const normalizedCode = normalizeStageKey(code);
  if (["retrieval_miss", "rerank_hurt", "failed"].includes(normalizedCode)) {
    return "danger";
  }
  if (["low_keyword_coverage", "context_noise"].includes(normalizedCode)) {
    return "warning";
  }
  return "neutral";
}

export function renderFailureReasonTag(reason) {
  const code = normalizeStageKey(reason.code);
  const className = getFailureReasonClass(code);
  const countText = hasValue(reason.count) ? ` \u00D7${formatFieldValue(reason.count)}` : "";
  return `<span class="failure-tag ${escapeHtml(className)}">${escapeHtml(code)}${escapeHtml(countText)}</span>`;
}

export function renderRagFailureLens(entries) {
  if (!entries || entries.length === 0) {
    return `
      <div class="detail-block rag-debug-block failure-lens-block">
        <h4>Failure Lens</h4>
        <p class="block-note">\u540E\u7AEF\u8FD8\u6CA1\u6709\u8FD4\u56DE failure_reasons\uFF1Bretrieval_miss\u3001low_keyword_coverage\u3001rerank_hurt\u3001context_noise \u4F1A\u5728\u8FD9\u91CC\u6C47\u603B\u3002</p>
      </div>
    `;
  }

  return `
    <div class="detail-block rag-debug-block failure-lens-block">
      <h4>Failure Lens</h4>
      <div class="failure-lens-list">
        ${entries.slice(0, 14).map((entry) => `
          <article class="failure-lens-row">
            <div>
              <strong>${escapeHtml(truncateText(entry.caseId, 44))}</strong>
              ${hasValue(entry.configName) ? `<span class="config-chip">${escapeHtml(truncateText(entry.configName, 28))}</span>` : ""}
            </div>
            <div class="failure-tags">
              ${entry.reasons.map((reason) => renderFailureReasonTag(reason)).join("")}
            </div>
            ${hasValue(entry.note) ? `<p class="block-note">${escapeHtml(truncateText(entry.note, 140))}</p>` : ""}
          </article>
        `).join("")}
      </div>
    </div>
  `;
}

export function renderRagLabSummary(data) {
  const configs = normalizeRagConfigResults(data || {});
  const metrics = getRagSummaryMetrics(data || {}, configs);
  const cases = getRagCases(data || {}, configs);
  const rankings = getRagRankingPreviews(data || {}, cases, configs);
  const failures = getRagFailures(data || {}, cases, configs);
  const flightRecords = getRagFlightRecorders(data || {}, cases, configs);
  const courtroomRows = getRagCourtroom(data || {}, cases, configs);
  const failureLens = getRagFailureLens(data || {}, cases, failures, configs, courtroomRows);

  summaryOutput.innerHTML = `
    <div class="summary-block primary">
      <h3>RAG Debugger</h3>
      ${renderMetricCards(metrics)}
    </div>
    <div class="summary-block">
      <h3>\u8FD0\u884C\u914D\u7F6E</h3>
      ${renderRagConfigStrip(data || {}, configs)}
    </div>
  `;

  detailOutput.innerHTML = `
    ${renderRagFlightRecorder(flightRecords)}
    ${renderRagCourtroom(courtroomRows)}
    ${renderRagFailureLens(failureLens)}
    ${renderRagCaseCards(cases)}
    ${flightRecords.length > 0 ? "" : renderRagRankingPreviews(rankings)}
    ${renderRagFailures(failures)}
  `;
}

export function renderRagFailures(failures) {
  if (!failures || failures.length === 0) {
    return `<div class="detail-block"><h4>Failures</h4><p class="block-note">\u5F53\u524D\u7ED3\u679C\u6CA1\u6709\u8FD4\u56DE\u5931\u8D25\u6837\u4F8B\u3002</p></div>`;
  }
  return `
    <div class="detail-block">
      <h4>Failures</h4>
      <div class="failure-list">
        ${failures.map((item, index) => {
          const failure = isPlainObject(item) ? item : { reason: item };
          const caseId = firstPresent(failure.case_id, failure.id, failure.name, `failure_${index + 1}`);
          const question = firstPresent(failure.question, failure.query, failure.input);
          const reason = firstPresent(failure.reason, failure.error, failure.message, failure.answer, failure.response);
          return `
            <article class="failure-card">
              <header>
                <strong>${escapeHtml(formatFieldValue(caseId))}</strong>
                ${hasValue(failure.config_name) ? `<span class="config-chip">${escapeHtml(formatFieldValue(failure.config_name))}</span>` : ""}
              </header>
              ${hasValue(question) ? `<p class="block-note">${escapeHtml(formatFieldValue(question))}</p>` : ""}
              ${renderKeyValuePills(failure, ["case_id", "id", "name", "question", "query", "input", "reason", "error", "message", "answer", "response"])}
              ${hasValue(reason) ? `<p>${escapeHtml(formatFieldValue(reason))}</p>` : ""}
            </article>
          `;
        }).join("")}
      </div>
    </div>
  `;
}
