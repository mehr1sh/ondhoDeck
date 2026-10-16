/** Typed wrappers for every /api/v1 endpoint used by the frontend. */
import { api, apiRequest, newIdempotencyKey, streamChatReply } from "@/lib/api";
import type {
  AIProvider,
  AIProvidersOut,
  ChatDetailOut,
  ChatOut,
  ApplyOut,
  AssetIn,
  AssetOut,
  AssetUpdate,
  AuditOut,
  BlindSpotOut,
  BlindSpotSummary,
  ConstraintSupersede,
  FirmMemberIn,
  FirmMemberOut,
  FirmOut,
  FirmRole,
  FundDetail,
  FundDocumentInitiate,
  FundDocumentUpdate,
  FundIn,
  FundOut,
  FundTermsOut,
  FundType,
  FundUpdate,
  ReviewQueueOut,
  ReportsOut,
  ScenarioListItem,
  CashFlowIn,
  CashFlowOut,
  CashFlowUpdate,
  ConstraintDecision,
  ConstraintDetail,
  ConstraintOut,
  ConstraintUpdate,
  CredentialIn,
  CredentialOut,
  CredentialTestOut,
  CredentialUpdate,
  DocumentInitiate,
  DocumentInitiateOut,
  DocumentOut,
  EventIn,
  EventOut,
  EventUpdate,
  ExportIn,
  ExportOut,
  HouseholdIn,
  HouseholdOut,
  HouseholdSummary,
  HouseholdUpdate,
  JobOut,
  LiabilityIn,
  LiabilityOut,
  LiabilityUpdate,
  Page,
  PageOut,
  PreventionOut,
  PreventionRequest,
  ProfileOut,
  ProviderModelsOut,
  ProfileUpdate,
  RecommendationDecision,
  RecommendationOut,
  ReviewStatus,
  RunDetail,
  RunSummary,
  ScenarioDefaults,
  ScenarioIn,
  ScenarioOut,
  ScenarioPreset,
  ScenarioUpdate,
  SignedUrlOut,
  StressOut,
  StressRequest,
} from "@/lib/types";

export interface PageQuery {
  limit?: number;
  offset?: number;
}

const pq = (q?: PageQuery) => ({ limit: q?.limit, offset: q?.offset });

export const endpoints = {
  // profile
  getMe: () => api.get<ProfileOut>("/me"),
  updateMe: (body: ProfileUpdate) => api.patch<ProfileOut>("/me", body),
  deleteMe: () => api.del("/me", { confirm: "DELETE MY ACCOUNT" }),
  myDocuments: (q?: PageQuery) => api.get<Page<DocumentOut>>("/me/documents", pq(q)),

  // AI provider keys (BYOK). The key is only ever sent in a request body, never in a URL.
  aiProviders: () => api.get<AIProvidersOut>("/me/ai-providers"),
  saveAiCredential: (provider: AIProvider, body: CredentialIn) =>
    api.put<CredentialTestOut>(`/me/ai-providers/${provider}`, body),
  testAiCredential: (provider: AIProvider) => api.post<CredentialTestOut>(`/me/ai-providers/${provider}/test`, {}),
  aiProviderModels: (provider: AIProvider) => api.get<ProviderModelsOut>(`/me/ai-providers/${provider}/models`),
  updateAiCredential: (provider: AIProvider, body: CredentialUpdate) =>
    api.patch<CredentialOut>(`/me/ai-providers/${provider}`, body),
  deleteAiCredential: (provider: AIProvider) => api.del(`/me/ai-providers/${provider}`),

  // households
  listHouseholds: (q?: PageQuery) => api.get<Page<HouseholdOut>>("/households", pq(q)),
  createHousehold: (body: HouseholdIn) => api.post<HouseholdOut>("/households", body),
  createDemoHousehold: () => api.post<HouseholdOut>("/households/demo", {}),
  getHousehold: (hid: string) => api.get<HouseholdOut>(`/households/${hid}`),
  updateHousehold: (hid: string, body: HouseholdUpdate) => api.patch<HouseholdOut>(`/households/${hid}`, body),
  deleteHousehold: (hid: string) => api.del(`/households/${hid}`),
  householdSummary: (hid: string) => api.get<HouseholdSummary>(`/households/${hid}/summary`),
  auditEvents: (hid: string, q?: PageQuery) => api.get<Page<AuditOut>>(`/households/${hid}/audit-events`, pq(q)),
  aiProviderEvents: (q?: PageQuery) => api.get<Page<AuditOut>>("/me/ai-providers-events", pq(q)),

  // financial records
  listAssets: (hid: string, q?: PageQuery) => api.get<Page<AssetOut> | AssetOut[]>(`/households/${hid}/assets`, pq(q)),
  createAsset: (hid: string, body: AssetIn) => api.post<AssetOut>(`/households/${hid}/assets`, body),
  updateAsset: (id: string, body: AssetUpdate) => api.patch<AssetOut>(`/assets/${id}`, body),
  deleteAsset: (id: string) => api.del(`/assets/${id}`),

  listLiabilities: (hid: string, q?: PageQuery) =>
    api.get<Page<LiabilityOut> | LiabilityOut[]>(`/households/${hid}/liabilities`, pq(q)),
  createLiability: (hid: string, body: LiabilityIn) => api.post<LiabilityOut>(`/households/${hid}/liabilities`, body),
  updateLiability: (id: string, body: LiabilityUpdate) => api.patch<LiabilityOut>(`/liabilities/${id}`, body),
  deleteLiability: (id: string) => api.del(`/liabilities/${id}`),

  listCashFlows: (hid: string, q?: PageQuery) =>
    api.get<Page<CashFlowOut> | CashFlowOut[]>(`/households/${hid}/cash-flows`, pq(q)),
  createCashFlow: (hid: string, body: CashFlowIn) => api.post<CashFlowOut>(`/households/${hid}/cash-flows`, body),
  updateCashFlow: (id: string, body: CashFlowUpdate) => api.patch<CashFlowOut>(`/cash-flows/${id}`, body),
  deleteCashFlow: (id: string) => api.del(`/cash-flows/${id}`),

  listEvents: (hid: string, q?: PageQuery) => api.get<Page<EventOut> | EventOut[]>(`/households/${hid}/events`, pq(q)),
  createEvent: (hid: string, body: EventIn) => api.post<EventOut>(`/households/${hid}/events`, body),
  updateEvent: (id: string, body: EventUpdate) => api.patch<EventOut>(`/events/${id}`, body),
  deleteEvent: (id: string) => api.del(`/events/${id}`),

  // documents
  listDocuments: (hid: string, q?: PageQuery) => api.get<Page<DocumentOut>>(`/households/${hid}/documents`, pq(q)),
  initiateUpload: (hid: string, body: DocumentInitiate) =>
    api.post<DocumentInitiateOut>(`/households/${hid}/documents`, body),
  uploadContent: (url: string, file: Blob, contentType = "application/pdf") =>
    apiRequest<DocumentOut | undefined>(url, { method: "PUT", rawBody: file, contentType, absoluteUrl: true }),
  completeUpload: (docId: string, idempotencyKey = newIdempotencyKey()) =>
    api.post<JobOut>(`/documents/${docId}/complete`, {}, { idempotencyKey }),
  getDocument: (docId: string) => api.get<DocumentOut>(`/documents/${docId}`),
  documentJobs: (docId: string) => api.get<Page<JobOut> | JobOut[]>(`/documents/${docId}/jobs`),
  retryDocument: (docId: string, idempotencyKey = newIdempotencyKey()) =>
    api.post<JobOut>(`/documents/${docId}/retry`, {}, { idempotencyKey }),
  downloadDocument: (docId: string) => api.get<SignedUrlOut>(`/documents/${docId}/download`),
  documentPage: (docId: string, pdfPage: number) => api.get<PageOut>(`/documents/${docId}/pages/${pdfPage}`),
  deleteDocument: (docId: string) => api.del(`/documents/${docId}`),
  getJob: (jobId: string) => api.get<JobOut>(`/jobs/${jobId}`),

  // constraints
  listConstraints: (
    hid: string,
    q?: PageQuery & { document_id?: string; review_status?: ReviewStatus | "" },
  ) =>
    api
      .get<Page<ConstraintOut> | ConstraintOut[]>(`/households/${hid}/constraints`, {
        ...pq(q),
        document_id: q?.document_id,
        review_status: q?.review_status,
      })
      // The API returns a plain array for this list; normalise to the page shape callers use.
      .then((r): Page<ConstraintOut> => {
        if (!Array.isArray(r)) return r;
        return { items: r, total: r.length, limit: r.length, offset: 0 };
      }),
  getConstraint: (cid: string) => api.get<ConstraintDetail>(`/constraints/${cid}`),
  updateConstraint: (cid: string, body: ConstraintUpdate) => api.patch<ConstraintDetail>(`/constraints/${cid}`, body),
  approveConstraint: (cid: string, body: ConstraintDecision) =>
    api.post<ConstraintDetail>(`/constraints/${cid}/approve`, body),
  rejectConstraint: (cid: string, body: ConstraintDecision) =>
    api.post<ConstraintDetail>(`/constraints/${cid}/reject`, body),
  /** Marks `cid` (the newer term) as superseding an older approved term of the same type. */
  supersedeConstraint: (cid: string, body: ConstraintSupersede) =>
    api.post<ConstraintOut[]>(`/constraints/${cid}/supersede`, body),

  // scenarios & runs
  scenarioDefaults: () => api.get<ScenarioDefaults>("/scenario-defaults"),
  scenarioPresets: () => api.get<ScenarioPreset[]>("/scenario-presets"),
  listScenarios: (hid: string, q?: PageQuery) =>
    api.get<Page<ScenarioOut> | ScenarioOut[]>(`/households/${hid}/scenarios`, pq(q)),
  createScenario: (hid: string, body: ScenarioIn) => api.post<ScenarioOut>(`/households/${hid}/scenarios`, body),
  getScenario: (sid: string) => api.get<ScenarioOut>(`/scenarios/${sid}`),
  updateScenario: (sid: string, body: ScenarioUpdate) => api.patch<ScenarioOut>(`/scenarios/${sid}`, body),
  deleteScenario: (sid: string) => api.del(`/scenarios/${sid}`),
  runScenario: (sid: string, idempotencyKey = newIdempotencyKey()) =>
    api.post<RunSummary>(`/scenarios/${sid}/runs`, {}, { idempotencyKey }),
  listRuns: (hid: string, q?: PageQuery & { scenario_id?: string }) =>
    api.get<Page<RunSummary>>(`/households/${hid}/runs`, { ...pq(q), scenario_id: q?.scenario_id }),
  getRun: (runId: string) => api.get<RunDetail>(`/runs/${runId}`),

  // reverse stress
  runStress: (sid: string, body: StressRequest) => api.post<StressOut>(`/scenarios/${sid}/stress`, body),
  listStress: (hid: string, q?: PageQuery) => api.get<Page<StressOut>>(`/households/${hid}/stress-results`, pq(q)),
  getStress: (id: string) => api.get<StressOut>(`/stress-results/${id}`),

  // prevention
  runPrevention: (sid: string, body: PreventionRequest) =>
    api.post<PreventionOut>(`/scenarios/${sid}/prevention`, body),
  listPrevention: (hid: string, q?: PageQuery) =>
    api.get<Page<PreventionOut>>(`/households/${hid}/prevention-plans`, pq(q)),
  getPrevention: (id: string) => api.get<PreventionOut>(`/prevention-plans/${id}`),
  decideRecommendation: (id: string, body: RecommendationDecision) =>
    api.post<RecommendationOut>(`/recommendations/${id}/decision`, body),
  applyRecommendation: (id: string) => api.post<ApplyOut>(`/recommendations/${id}/apply`, {}),

  // blind-spot detector
  runBlindSpots: (sid: string, idempotencyKey = newIdempotencyKey()) =>
    api.post<BlindSpotOut>(`/scenarios/${sid}/blind-spots`, {}, { idempotencyKey }),
  listBlindSpotReports: (hid: string, q?: PageQuery & { scenario_id?: string }) =>
    api.get<Page<BlindSpotSummary>>(`/households/${hid}/blind-spot-reports`, { ...pq(q), scenario_id: q?.scenario_id }),
  getBlindSpotReport: (id: string) => api.get<BlindSpotOut>(`/blind-spot-reports/${id}`),

  // exports
  listExports: (hid: string, q?: PageQuery) => api.get<Page<ExportOut>>(`/households/${hid}/exports`, pq(q)),
  requestExport: (hid: string, body: ExportIn) => api.post<ExportOut>(`/households/${hid}/exports`, body),
  getExport: (id: string) => api.get<ExportOut>(`/exports/${id}`),
  downloadExport: (id: string) => api.get<SignedUrlOut>(`/exports/${id}/download`),

  // workspace (cross-household)
  reviewQueue: (limit?: number) => api.get<ReviewQueueOut>("/me/review-queue", { limit }),
  myScenarios: () => api.get<ScenarioListItem[]>("/me/scenarios"),
  myReports: (limit?: number) => api.get<ReportsOut>("/me/reports", { limit }),

  // assistant (answers with the user's own AI provider key)
  listChats: (householdId?: string | null) =>
    api.get<ChatOut[]>("/chats", { household_id: householdId ?? undefined }),
  createChat: (householdId?: string | null) => api.post<ChatOut>("/chats", { household_id: householdId ?? null }),
  getChat: (id: string) => api.get<ChatDetailOut>(`/chats/${id}`),
  deleteChat: (id: string) => api.del(`/chats/${id}`),
  /** Streams the reply: `onDelta` gets text as it arrives; resolves with both saved messages. */
  sendChatMessage: (id: string, content: string, onDelta: (text: string) => void, signal?: AbortSignal) =>
    streamChatReply(`/chats/${id}/messages`, { content }, onDelta, signal),

  // firms
  myFirms: () => api.get<FirmOut[]>("/me/firms"),
  renameFirm: (firmId: string, name: string) => api.patch<FirmOut>(`/firms/${firmId}`, { name }),
  firmMembers: (firmId: string) => api.get<FirmMemberOut[]>(`/firms/${firmId}/members`),
  addFirmMember: (firmId: string, body: FirmMemberIn) => api.post<FirmMemberOut[]>(`/firms/${firmId}/members`, body),
  changeFirmMemberRole: (firmId: string, userId: string, role: FirmRole) =>
    api.patch<FirmMemberOut[]>(`/firms/${firmId}/members/${userId}`, { role }),
  removeFirmMember: (firmId: string, userId: string) => api.del(`/firms/${firmId}/members/${userId}`),

  // fund library
  searchFunds: (
    q?: PageQuery & { q?: string; fund_type?: FundType | ""; include_archived?: boolean; firm_id?: string },
  ) =>
    api.get<Page<FundOut>>("/funds", {
      ...pq(q),
      q: q?.q?.trim() || undefined,
      fund_type: q?.fund_type || undefined,
      include_archived: q?.include_archived ? true : undefined,
      firm_id: q?.firm_id,
    }),
  createFund: (body: FundIn) => api.post<FundOut>("/funds", body),
  getFund: (fundId: string) => api.get<FundDetail>(`/funds/${fundId}`),
  updateFund: (fundId: string, body: FundUpdate) => api.patch<FundOut>(`/funds/${fundId}`, body),
  fundDocuments: (fundId: string) => api.get<DocumentOut[] | Page<DocumentOut>>(`/funds/${fundId}/documents`),
  initiateFundUpload: (fundId: string, body: FundDocumentInitiate) =>
    api.post<DocumentInitiateOut>(`/funds/${fundId}/documents`, body),
  updateLibraryDocument: (docId: string, body: FundDocumentUpdate) =>
    api.patch<DocumentOut>(`/documents/${docId}/library-metadata`, body),
  fundTerms: (fundId: string, asOf?: string) => api.get<FundTermsOut>(`/funds/${fundId}/terms`, { as_of: asOf }),
  fundAudit: (fundId: string, q?: PageQuery) => api.get<Page<AuditOut>>(`/funds/${fundId}/audit-events`, pq(q)),
};
