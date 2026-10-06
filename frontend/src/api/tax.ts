import { api } from "./client";
import type { Schemas } from "./types";

/* The reader's declared tax rates. Three keys in the backend's `settings`
   table, reached through a typed resource rather than a generic key/value
   door — see backend/app/routers/settings.py for why that door stays shut.

   Rates are PERCENT here and everywhere else (26 means 26%): the app already
   stores one rate that way (a liability's interest rate), and a codebase where
   26 means 26% in one place and 0.26 means it in another has a factor-of-100
   bug waiting for whoever guesses wrong. */
export type TaxSettings = Schemas["TaxSettings"];
export type TaxSettingsRead = Schemas["TaxSettingsRead"];
export type TaxCountryDefault = Schemas["TaxCountryDefault"];
export type TaxEstimate = Schemas["TaxEstimate"];

// GET /api/settings/tax — the current values AND the countries this app ships
// a default for, in one round trip so the table has a single source.
export async function getTaxSettings(): Promise<TaxSettingsRead> {
  return (await api.get<TaxSettingsRead>("/api/settings/tax")).data;
}

// Replaces all three. A null clears that key: "I have not said" rather than
// the 0 that would claim "I pay nothing".
export async function saveTaxSettings(
  data: TaxSettings,
): Promise<TaxSettingsRead> {
  return (await api.put<TaxSettingsRead>("/api/settings/tax", data)).data;
}
