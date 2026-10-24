import type { components } from "@/types/api";

type Schemas = components["schemas"];

export type PlatformMe = Schemas["PlatformMe"];
export type CompanySummary = Schemas["CompanySummary"];
export type CompanyPage = Schemas["CompanyPage"];
export type CompanyDetail = Schemas["CompanyDetail"];
export type CompanyUser = Schemas["CompanyUser"];
export type WorkersHealth = Schemas["WorkersHealth"];
export type JobHealth = Schemas["JobHealth"];
export type ComponentHealth = Schemas["ComponentHealth"];
export type JobRun = Schemas["JobRun"];
export type JobRunPage = Schemas["JobRunPage"];
export type PlatformOutbox = Schemas["PlatformOutbox"];
export type PlanRead = Schemas["PlanRead"];
export type SubscriptionDetail = Schemas["SubscriptionDetail"];
export type SupportSessionRead = Schemas["SupportSessionRead"];
export type SupportSessionList = Schemas["SupportSessionList"];
export type SupportAccessToken = Schemas["SupportAccessToken"];
