import { api } from "./client";
import type { Schemas } from "./types";

/* The currency every total is shown in, and the ones it can become.

   A typed resource beside the tax settings, for the same reason: the settings
   table holds keys the browser must not reach, so each one somebody actually
   sets has its own door. The list of choices comes from the ECB feed, because
   a total can only be converted into a currency somebody publishes a rate for. */
export type BaseCurrencySetting = Schemas["BaseCurrencySettingRead"];

// GET /api/settings/base-currency
export async function getBaseCurrency(): Promise<BaseCurrencySetting> {
  return (await api.get<BaseCurrencySetting>("/api/settings/base-currency")).data;
}

// PUT /api/settings/base-currency — refused (503) when the new base's rates
// cannot be stored first, and nothing changes then.
export async function saveBaseCurrency(code: string): Promise<BaseCurrencySetting> {
  return (
    await api.put<BaseCurrencySetting>("/api/settings/base-currency", { base_currency: code }, { timeout: 60_000 })
  ).data;
}
