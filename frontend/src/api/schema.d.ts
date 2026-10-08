/**
 * GENERATED FILE — do not edit by hand.
 *
 * Produced from the backend's OpenAPI document by `npm run gen:types`, which
 * `npm run build` runs before tsc. To change a type here, change the Pydantic
 * model in backend/app/schemas.py and rebuild: this file is the transcription
 * that used to be done by hand, and drifted.
 */

export interface paths {
    "/api/accumulation-plans": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * List Accumulation Plans
         * @description List all accumulation plans.
         */
        get: operations["list_accumulation_plans_api_accumulation_plans_get"];
        put?: never;
        /**
         * Create Accumulation Plan
         * @description Create a new accumulation plan (404 if a linked institution doesn't exist).
         *
         *     `AccumulationPlanWrite` rather than `AccumulationPlanCreate`: a plan posted
         *     here must say where the money comes from and where each position will be
         *     held. Money moves from an account into a holding, and a plan that names
         *     neither end is describing a purchase nobody made — see the schema for the
         *     total it moved when it did.
         */
        post: operations["create_accumulation_plan_api_accumulation_plans_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/accumulation-plans/{plan_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Accumulation Plan
         * @description Return a single accumulation plan, or 404 if it does not exist.
         */
        get: operations["get_accumulation_plan_api_accumulation_plans__plan_id__get"];
        /**
         * Update Accumulation Plan
         * @description Update an accumulation plan (404 if it or a linked institution doesn't exist).
         *
         *     The same requirement as the POST, and this is the door a plan saved without
         *     either end is repaired through: naming them is a two-field edit. The GET
         *     keeps returning such a plan unchanged, so it can be read before it is
         *     fixed.
         */
        put: operations["update_accumulation_plan_api_accumulation_plans__plan_id__put"];
        post?: never;
        /**
         * Delete Accumulation Plan
         * @description Delete an accumulation plan.
         */
        delete: operations["delete_accumulation_plan_api_accumulation_plans__plan_id__delete"];
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/advisor/chain": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * List Chain Runs
         * @description Every analysis run, newest first: when, how deep, and whether it argued.
         *
         *     The summary is computed here rather than stored, and that is what makes it
         *     true of runs that finished before anyone thought to ask the question. The
         *     marker was already in the confidant's own text; nothing was migrated and
         *     nothing had to be.
         */
        get: operations["list_chain_runs_api_advisor_chain_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/advisor/chain/{run_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Chain Run
         * @description One analysis run: the verdict, and every step behind it.
         */
        get: operations["get_chain_run_api_advisor_chain__run_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/cash-anchors": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * List All Cash Anchors
         * @description Every institution's cash anchors, by institution then date — in one
         *     request. A form that proposes the currency of an account on a date needs
         *     the anchor in force then for whichever account the reader picks, and
         *     asking per account would be one request for each of them.
         */
        get: operations["list_all_cash_anchors_api_cash_anchors_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/cash-anchors/{anchor_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Cash Anchor
         * @description Return a single cash anchor, or 404 if it does not exist.
         */
        get: operations["get_cash_anchor_api_cash_anchors__anchor_id__get"];
        /**
         * Update Cash Anchor
         * @description Update a cash anchor (409 if another anchor exists for that date).
         */
        put: operations["update_cash_anchor_api_cash_anchors__anchor_id__put"];
        post?: never;
        /**
         * Delete Cash Anchor
         * @description Delete a cash anchor.
         */
        delete: operations["delete_cash_anchor_api_cash_anchors__anchor_id__delete"];
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/cash/positions": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * List Cash Positions
         * @description Projected cash for every institution at `as_of` (default today).
         */
        get: operations["list_cash_positions_api_cash_positions_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/chat": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Send
         * @description Ask one more question, streaming the reply. No conversation id opens a
         *     new conversation; the `start` event says which.
         *
         *     Configuration problems (no key, no package) arrive as an `error` event
         *     rather than a 503: the client has one path for "this stopped, and here is
         *     why", whichever moment it stopped at. A conversation that does not exist
         *     is the one thing refused before the stream: there is nowhere to store the
         *     question.
         */
        post: operations["send_api_chat_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/chat/cards/{card_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Decide
         * @description Confirm or reject one proposed write, and stream what the model says
         *     about it.
         *
         *     On confirm the tool runs first, inside one unit of work with the record of
         *     it, so the card cannot end up reading "confirmed" over a write that rolled
         *     back. Only then does the stream start. The analyzer is the exception and
         *     keeps the guarantee that matters: its run is written before its card is
         *     settled, so the ordering can fail into a run no receipt names and never
         *     into a receipt over a run that did not happen.
         *
         *     Three refusals, all of them BEFORE the first byte, because a refusal
         *     arriving mid-stream is one the client has to fish out of an event — except
         *     for the analyzer, whose work is a minute long and therefore happens ON the
         *     stream. Its card is still checked here and cannot be decided twice; what
         *     moves is only the running, and a refusal that surfaces after it started
         *     arrives as an `error` event, because by then there is no status line left
         *     to send:
         *
         *       404  no card with that id
         *       409  it has already been confirmed or rejected — a decision is taken
         *            once, and a second confirm would write the row twice
         *       409  it is stale: what it was drawn against has moved since it was
         *            proposed, so what the card says would happen is no longer what
         *            would happen
         *
         *     Anything the model itself fails at afterwards arrives as an `error` event,
         *     the same as any other turn — by then the write has happened and the reader
         *     is owed the stream, not a status code. Which is why the stream says the
         *     decision first: `decided`, the card as stored, right after `start` (for
         *     the analyzer, once its run is stored), so a failure after it cannot leave
         *     the card looking undecided.
         */
        post: operations["decide_api_chat_cards__card_id__post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/chat/conversations": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * List Conversations
         * @description Every conversation, most recently spoken to first — the history list.
         */
        get: operations["list_conversations_api_chat_conversations_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/chat/conversations/{conversation_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Conversation
         * @description One conversation with every turn, oldest first, each card in the
         *     reader's words (`tools.present`), as the stream sends it.
         */
        get: operations["get_conversation_api_chat_conversations__conversation_id__get"];
        put?: never;
        post?: never;
        /**
         * Delete Conversation
         * @description Forget a conversation and every turn in it.
         */
        delete: operations["delete_conversation_api_chat_conversations__conversation_id__delete"];
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/chat/models": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Models
         * @description The model dropdown, default first.
         */
        get: operations["get_models_api_chat_models_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/dashboard/allocation": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Allocation
         * @description Allocation: financial by asset class, real by category.
         */
        get: operations["get_allocation_api_dashboard_allocation_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/dashboard/cashflow": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Cashflow
         * @description The income and expenses in force today as a monthly run-rate, the
         *     savings rate and the splits, and the flows left out: the ones still to
         *     start and the ones that have ended.
         */
        get: operations["get_cashflow_api_dashboard_cashflow_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/dashboard/net-worth-series": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Net Worth Series
         * @description Net worth over time (carry-forward), summing accounts and real assets.
         */
        get: operations["get_net_worth_series_api_dashboard_net_worth_series_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/dashboard/portfolio": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Portfolio
         * @description Investment positions (latest snapshot per institution). With ?live=true,
         *     fetch market prices (one batch) and update the price cache; otherwise reuse
         *     cached prices. Market value + P/L are computed vs the recorded value.
         */
        get: operations["get_portfolio_api_dashboard_portfolio_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/dashboard/portfolio/composition": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Portfolio Composition
         * @description Look-through composition of the whole portfolio: aggregated country and
         *     sector exposure plus cross-fund holding overlap. Per-symbol data comes
         *     from the 15-day cache; ?refresh=true forces a refetch from the sources
         *     (justETF / Morningstar / Yahoo). Positions no source can decompose stay
         *     whole and lower `coverage_pct` — honestly.
         */
        get: operations["get_portfolio_composition_api_dashboard_portfolio_composition_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/dashboard/summary": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Summary
         * @description Net worth (financial + real) and a few counts.
         */
        get: operations["get_summary_api_dashboard_summary_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/expenses": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List all expenses */
        get: operations["list_items_api_expenses_get"];
        put?: never;
        /** Create a new expense */
        post: operations["create_item_api_expenses_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/expenses/{item_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Return a single expense, or 404 if it does not exist */
        get: operations["get_item_api_expenses__item_id__get"];
        /** Update an expense */
        put: operations["update_item_api_expenses__item_id__put"];
        post?: never;
        /** Delete an expense */
        delete: operations["delete_item_api_expenses__item_id__delete"];
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/fx/rates": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Fx Rates
         * @description The ECB reference rates in force today against the base (units per 1
         *     base): the latest published day, asked for at most once a day. Empty until
         *     the first successful fetch; ?refresh=true asks again. Each row names its
         *     base and its day, so a rate is never a bare number here either.
         */
        get: operations["get_fx_rates_api_fx_rates_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/goals": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * List Goals
         * @description List all goals.
         */
        get: operations["list_goals_api_goals_get"];
        put?: never;
        /**
         * Create Goal
         * @description Create a new goal.
         */
        post: operations["create_goal_api_goals_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/goals/{goal_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Goal
         * @description Return a single goal, or 404 if it does not exist.
         */
        get: operations["get_goal_api_goals__goal_id__get"];
        /**
         * Update Goal
         * @description Update a goal.
         */
        put: operations["update_goal_api_goals__goal_id__put"];
        post?: never;
        /**
         * Delete Goal
         * @description Delete a goal.
         */
        delete: operations["delete_goal_api_goals__goal_id__delete"];
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/health": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Health
         * @description Healthcheck: confirms the backend is up.
         */
        get: operations["health_api_health_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/holdings/{holding_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Holding
         * @description Return a single holding, or 404 if it does not exist.
         */
        get: operations["get_holding_api_holdings__holding_id__get"];
        /**
         * Update Holding
         * @description Update a holding (value recomputed from quantity*price if not given).
         */
        put: operations["update_holding_api_holdings__holding_id__put"];
        post?: never;
        /**
         * Delete Holding
         * @description Delete a holding.
         */
        delete: operations["delete_holding_api_holdings__holding_id__delete"];
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/holdings/{holding_id}/refresh-price": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Refresh Holding Price
         * @description Fetch the live quote for a holding's symbol and update its unit price
         *     (recomputing value if the holding is quantity-based).
         */
        post: operations["refresh_holding_price_api_holdings__holding_id__refresh_price_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/income-sources": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List all income sources */
        get: operations["list_items_api_income_sources_get"];
        put?: never;
        /** Create a new income source */
        post: operations["create_item_api_income_sources_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/income-sources/{item_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Return a single income source, or 404 if it does not exist */
        get: operations["get_item_api_income_sources__item_id__get"];
        /** Update an income source */
        put: operations["update_item_api_income_sources__item_id__put"];
        post?: never;
        /** Delete an income source */
        delete: operations["delete_item_api_income_sources__item_id__delete"];
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/institutions": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * List Institutions
         * @description List all institutions.
         */
        get: operations["list_institutions_api_institutions_get"];
        put?: never;
        /**
         * Create Institution
         * @description Create a new institution.
         */
        post: operations["create_institution_api_institutions_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/institutions/{institution_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Institution
         * @description Return a single institution, or 404 if it does not exist.
         */
        get: operations["get_institution_api_institutions__institution_id__get"];
        /**
         * Update Institution
         * @description Update an institution.
         */
        put: operations["update_institution_api_institutions__institution_id__put"];
        post?: never;
        /**
         * Delete Institution
         * @description Delete an institution (cascades to its accounts, snapshots and holdings).
         */
        delete: operations["delete_institution_api_institutions__institution_id__delete"];
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/institutions/{institution_id}/cash": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Cash Position
         * @description Projected cash for the institution at `as_of` (default today), with its
         *     breakdown (anchor, income, expenses, transfers).
         */
        get: operations["get_cash_position_api_institutions__institution_id__cash_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/institutions/{institution_id}/cash-anchors": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * List Cash Anchors
         * @description List an institution's cash anchors (chronological order).
         */
        get: operations["list_cash_anchors_api_institutions__institution_id__cash_anchors_get"];
        put?: never;
        /**
         * Create Cash Anchor
         * @description Create a dated cash anchor for the institution (409 if that date exists).
         */
        post: operations["create_cash_anchor_api_institutions__institution_id__cash_anchors_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/institutions/{institution_id}/snapshots": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * List Snapshots
         * @description List an institution's snapshots (chronological order).
         */
        get: operations["list_snapshots_api_institutions__institution_id__snapshots_get"];
        put?: never;
        /**
         * Create Snapshot
         * @description Create a dated snapshot for the institution (409 if that date exists).
         */
        post: operations["create_snapshot_api_institutions__institution_id__snapshots_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/institutions/{institution_id}/snapshots/prefilled": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Create Prefilled Snapshot
         * @description A new dated situation, starting from the positions of the previous one.
         *
         *     The newest snapshot is the authority for the whole institution, so one that
         *     omits a position deletes it — which is why updating a single number
         *     otherwise means re-declaring the entire account from memory. Here the list
         *     arrives already filled: everything with a ticker is re-priced for the new
         *     date, and `needs_attention` names the rows nothing could re-price, which
         *     are exactly the ones worth looking at.
         *
         *     409 if a snapshot already exists on that date; 404 if there is nothing to
         *     prefill from.
         */
        post: operations["create_prefilled_snapshot_api_institutions__institution_id__snapshots_prefilled_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/instruments/catalogue": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Catalogue Status
         * @description What the registry holds and when it was last downloaded.
         */
        get: operations["catalogue_status_api_instruments_catalogue_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/instruments/catalogue/ensure": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Ensure Catalogue
         * @description Asked at every page load. Starts a download in the background when the
         *     catalogue is missing or a week old and none is running, and answers at once
         *     with where things stand: nobody presses anything for the catalogue.
         */
        post: operations["ensure_catalogue_api_instruments_catalogue_ensure_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/instruments/catalogue/refresh": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Refresh Catalogue
         * @description Download now and wait for it, whatever the catalogue's age. No page calls
         *     it: it is the door for a download by hand, behind the same one-at-a-time
         *     guard as the app's own (409 while one runs). 502 if the source fails or
         *     sends something that is not a catalogue, the stored copy left exactly as it
         *     was, since a failed download must never leave the picker emptier than it
         *     found it.
         */
        post: operations["refresh_catalogue_api_instruments_catalogue_refresh_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/instruments/lookup": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Lookup Symbols
         * @description The live lane: shares, ETFs, crypto and futures — everything the fund
         *     catalogue cannot hold, and the only source of a symbol that actually
         *     prices.
         *
         *     Deliberately a SEPARATE endpoint from /search. The catalogue answers from
         *     SQLite in milliseconds; this one is a network call. Combining them would
         *     make the instant lane wait for the slow one, and would let an outage empty
         *     a list that had perfectly good local results to show.
         */
        get: operations["lookup_symbols_api_instruments_lookup_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/instruments/search": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Search Instruments
         * @description Instrument families matching `q`, local only.
         *
         *     Families, not rows: an accumulating fund and its distributing twin carry
         *     the same name and differ only in what they do with dividends, so showing
         *     one of a pair alone invites picking the wrong one without ever revealing
         *     there was a choice.
         */
        get: operations["search_instruments_api_instruments_search_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/liabilities": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * List Liabilities
         * @description List all liabilities.
         */
        get: operations["list_liabilities_api_liabilities_get"];
        put?: never;
        /**
         * Create Liability
         * @description Create a new liability (404 if the linked real asset does not exist).
         */
        post: operations["create_liability_api_liabilities_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/liabilities/{liability_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Liability
         * @description Return a single liability, or 404 if it does not exist.
         */
        get: operations["get_liability_api_liabilities__liability_id__get"];
        /**
         * Update Liability
         * @description Update a liability (404 if it, or the linked real asset, does not exist).
         */
        put: operations["update_liability_api_liabilities__liability_id__put"];
        post?: never;
        /**
         * Delete Liability
         * @description Delete a liability (cascades to its balances).
         */
        delete: operations["delete_liability_api_liabilities__liability_id__delete"];
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/liabilities/{liability_id}/balances": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * List Balances
         * @description List a liability's balances (chronological order).
         */
        get: operations["list_balances_api_liabilities__liability_id__balances_get"];
        put?: never;
        /**
         * Create Balance
         * @description Add a dated balance to a liability (409 if one already exists for that date).
         */
        post: operations["create_balance_api_liabilities__liability_id__balances_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/liability-balances/{balance_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        /**
         * Update Balance
         * @description Update a balance (409 if another balance exists for that liability+date).
         */
        put: operations["update_balance_api_liability_balances__balance_id__put"];
        post?: never;
        /**
         * Delete Balance
         * @description Delete a liability balance.
         */
        delete: operations["delete_balance_api_liability_balances__balance_id__delete"];
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/planning/required-return": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Required Return
         * @description Annual return needed to reach a dated target, plus a realism note.
         */
        post: operations["required_return_api_planning_required_return_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/prices/listing-currencies": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Listing Currencies
         * @description {symbol: currency} for every listing whose trading currency is known,
         *     from the price cache alone — no market call. What a ledger form proposes as
         *     the currency of a price, before anyone has typed one.
         */
        get: operations["get_listing_currencies_api_prices_listing_currencies_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/prices/quote": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Quote
         * @description Price for a Yahoo symbol (e.g. VWCE.MI, AAPL, BTC-EUR): the latest
         *     close, or the close on a given date when `on` is passed — which is what
         *     turns backfilling an old purchase into typing a date and a quantity.
         *
         *     A dated close comes back without a currency from the market, and the
         *     currency it is in is exactly what a ledger entry has to state. A listing's
         *     currency does not change, so the one the price cache has learned for the
         *     symbol is given with it; a symbol nothing has priced yet has none to give.
         */
        get: operations["get_quote_api_prices_quote_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/prices/resolve": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Resolve Isin
         * @description Suggest tickers for an ISIN (you may need to add a Yahoo suffix like .MI).
         */
        get: operations["resolve_isin_api_prices_resolve_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/real-asset-valuations/{valuation_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Valuation
         * @description Return a single valuation, or 404 if it does not exist.
         */
        get: operations["get_valuation_api_real_asset_valuations__valuation_id__get"];
        /**
         * Update Valuation
         * @description Update a valuation (409 if another valuation exists for that asset+date).
         */
        put: operations["update_valuation_api_real_asset_valuations__valuation_id__put"];
        post?: never;
        /**
         * Delete Valuation
         * @description Delete a real-asset valuation.
         */
        delete: operations["delete_valuation_api_real_asset_valuations__valuation_id__delete"];
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/real-assets": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * List Real Assets
         * @description List all real assets.
         */
        get: operations["list_real_assets_api_real_assets_get"];
        put?: never;
        /**
         * Create Real Asset
         * @description Create a new real asset.
         */
        post: operations["create_real_asset_api_real_assets_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/real-assets/{real_asset_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Real Asset
         * @description Return a single real asset, or 404 if it does not exist.
         */
        get: operations["get_real_asset_api_real_assets__real_asset_id__get"];
        /**
         * Update Real Asset
         * @description Update a real asset.
         */
        put: operations["update_real_asset_api_real_assets__real_asset_id__put"];
        post?: never;
        /**
         * Delete Real Asset
         * @description Delete a real asset (cascades to its valuations).
         */
        delete: operations["delete_real_asset_api_real_assets__real_asset_id__delete"];
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/real-assets/{real_asset_id}/valuations": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * List Valuations
         * @description List a real asset's valuations (chronological order).
         */
        get: operations["list_valuations_api_real_assets__real_asset_id__valuations_get"];
        put?: never;
        /**
         * Create Valuation
         * @description Add a dated valuation to a real asset (409 if one already exists for that date).
         */
        post: operations["create_valuation_api_real_assets__real_asset_id__valuations_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/settings/base-currency": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Base Currency
         * @description The currency every total is shown in, and the ones it can become: the
         *     currencies the ECB feed quotes, because a total can only be converted into
         *     a currency somebody publishes a rate for.
         */
        get: operations["get_base_currency_api_settings_base_currency_get"];
        /**
         * Put Base Currency
         * @description Change the base. Every total moves — the history's too — because it is
         *     the same wealth in another unit; no recorded amount is rewritten.
         *
         *     422 for a currency the feed does not quote. 503, with nothing changed, when
         *     the rates against the new base cannot be stored first: see
         *     `fx.choose_base` for why a base is not chosen before its rates are in.
         */
        put: operations["put_base_currency_api_settings_base_currency_put"];
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/settings/tax": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Tax Settings
         * @description The declared rates, with the handful of countries this app ships a
         *     default for. The defaults come down as data to OFFER, never applied: a
         *     reader's own figure beats any table shipped here, and a rate that changed
         *     itself because a country field changed is a rate nobody declared.
         */
        get: operations["get_tax_settings_api_settings_tax_get"];
        /**
         * Put Tax Settings
         * @description Replace all three. A null clears that key, which is how the reader says
         *     they do not know a rate — distinct from writing 0, which claims they pay
         *     nothing.
         */
        put: operations["put_tax_settings_api_settings_tax_put"];
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/snapshots/{snapshot_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Snapshot
         * @description Return a single snapshot, or 404 if it does not exist.
         */
        get: operations["get_snapshot_api_snapshots__snapshot_id__get"];
        /**
         * Update Snapshot
         * @description Update a snapshot (409 if another snapshot exists for that institution+date).
         */
        put: operations["update_snapshot_api_snapshots__snapshot_id__put"];
        post?: never;
        /**
         * Delete Snapshot
         * @description Delete a snapshot (cascades to its holdings).
         */
        delete: operations["delete_snapshot_api_snapshots__snapshot_id__delete"];
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/snapshots/{snapshot_id}/holdings": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * List Holdings
         * @description List a snapshot's holdings.
         */
        get: operations["list_holdings_api_snapshots__snapshot_id__holdings_get"];
        put?: never;
        /**
         * Create Holding
         * @description Add a holding to the given snapshot.
         */
        post: operations["create_holding_api_snapshots__snapshot_id__holdings_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/survey": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Survey
         * @description Return all stored questionnaire answers.
         */
        get: operations["get_survey_api_survey_get"];
        /**
         * Put Survey
         * @description Replace the whole set of answers with the provided ones.
         */
        put: operations["put_survey_api_survey_put"];
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/transactions": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * List Transactions
         * @description All recorded transactions, most recent first.
         */
        get: operations["list_transactions_api_transactions_get"];
        put?: never;
        /**
         * Create Transaction
         * @description Record a buy manually (a purchase made outside any PAC).
         *
         *     `TransactionWrite` rather than `TransactionCreate`: an entry posted here
         *     must name the institution holding it, because the cash has to leave a real
         *     account. The PAC writes through `crud` directly and keeps its looser
         *     payload — see the schema for what the difference is and why it is not a
         *     migration.
         */
        post: operations["create_transaction_api_transactions_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/transactions/{tx_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Transaction */
        get: operations["get_transaction_api_transactions__tx_id__get"];
        /**
         * Update Transaction
         * @description Correct a transaction with the real broker fill (clears `estimated`).
         *
         *     The same requirement as the POST, and this is the door an existing
         *     institution-less row is repaired through: attaching one is a one-field
         *     edit.
         */
        put: operations["update_transaction_api_transactions__tx_id__put"];
        post?: never;
        /** Delete Transaction */
        delete: operations["delete_transaction_api_transactions__tx_id__delete"];
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/transactions/catch-up": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Catch Up
         * @description Ledger catch-up (idempotent — safe to call at every app start): a Buy
         *     for every elapsed, still-unexecuted PAC occurrence at that day's close,
         *     and a dividend entry for every ex-date of every position that follows its
         *     dividends: stated distributing, or stating no policy, when its own history
         *     decides. Items that cannot be priced are skipped and retried on the next
         *     run.
         */
        post: operations["catch_up_api_transactions_catch_up_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/transfers": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * List Transfers
         * @description List all transfers (chronological order).
         */
        get: operations["list_transfers_api_transfers_get"];
        put?: never;
        /**
         * Create Transfer
         * @description Create a cash transfer between institutions.
         */
        post: operations["create_transfer_api_transfers_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/transfers/{transfer_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Transfer
         * @description Return a single transfer, or 404 if it does not exist.
         */
        get: operations["get_transfer_api_transfers__transfer_id__get"];
        /**
         * Update Transfer
         * @description Update a transfer. A `to_amount` sent empty is worked out again, at the
         *     rate final for the (possibly new) date; one left OUT of the body is not
         *     touched at all, like every other column the request does not mention —
         *     see `crud._update`.
         */
        put: operations["update_transfer_api_transfers__transfer_id__put"];
        post?: never;
        /**
         * Delete Transfer
         * @description Delete a transfer.
         */
        delete: operations["delete_transfer_api_transfers__transfer_id__delete"];
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/watchlist": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * List Watchlist
         * @description Every idea on the list, most recently added first.
         */
        get: operations["list_watchlist_api_watchlist_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/watchlist/{item_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        post?: never;
        /**
         * Delete Watchlist Item
         * @description Drop one idea. It owned nothing, so nothing is recomputed.
         */
        delete: operations["delete_watchlist_item_api_watchlist__item_id__delete"];
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
}
export type webhooks = Record<string, never>;
export interface components {
    schemas: {
        /**
         * AccumulationPlanRead
         * @description A stored accumulation plan as returned by the API.
         */
        AccumulationPlanRead: {
            /**
             * Amount
             * @description Amount contributed per occurrence
             */
            amount: number;
            /**
             * Carried Remainder
             * @description What the last whole-unit contribution could not place, waiting for the next one. Shown because money set aside and not yet invested is a fact the saver is entitled to see, not an implementation detail.
             * @default 0
             */
            carried_remainder: number;
            /** Created At */
            created_at: string;
            /**
             * Currency
             * @description Currency the contribution is paid in: the source account's cash, e.g. EUR
             */
            currency: string;
            /**
             * End Date
             * @description Last contribution (optional)
             */
            end_date: string | null;
            /**
             * Execution
             * @description How the broker fills the order: whole_units (floor(amount/price), remainder stays in cash — default) | fractional (exactly `amount`)
             */
            execution: string | null;
            /**
             * Frequency
             * @description monthly | quarterly | semiannual | annual
             */
            frequency: string | null;
            /** Id */
            id: number;
            /**
             * Name
             * @description Plan name (e.g. 'PAC All-World')
             */
            name: string;
            /**
             * Notes
             * @description Free-form notes
             */
            notes: string | null;
            /**
             * Source Institution Id
             * @description Institution whose cash funds the plan
             */
            source_institution_id: number | null;
            /**
             * Start Date
             * @description First contribution
             */
            start_date: string | null;
            /** Targets */
            targets: components["schemas"]["PlanTargetRead"][];
        };
        /**
         * AccumulationPlanWrite
         * @description What a PERSON may post to `/api/accumulation-plans` — which is not the
         *     same thing as what the tables are able to store.
         *
         *     Both ends of the sentence are required here, and both are optional
         *     everywhere else. Money moves FROM an account INTO a holding, and a plan
         *     that names neither end describes a purchase nobody made:
         *
         *     - No SOURCE and no target institution is the defect `TransactionWrite`
         *       already closed on the ledger, reached through a second door. `pac.py`
         *       writes `cash_institution_id=plan.source_institution_id`, so with no
         *       source both institution columns of every buy it creates are null — and
         *       the cash register keeps only the entries belonging to the institution it
         *       is computing, where null equals no id there is. The cash side is skipped
         *       everywhere, the position side counts in full, and the plan's spending
         *       adds itself to the net worth. Measured on a scratch database: 1000.00 of
         *       cash, two elapsed occurrences of 100.00 each, net worth 1000.00 ->
         *       1200.00 with the cash untouched at 1000.00.
         *
         *     - No TARGET institution alone does not move a total: the source names the
         *       cash side and the arithmetic stays right to the cent. It creates a
         *       position held at no institution, which no situation can photograph, no
         *       snapshot can reconcile, and — since a `close` is matched to its position
         *       by institution — no disposal can settle. `ca4858d` called requiring this
         *       a separate decision; this is that decision.
         *
         *     The columns stay nullable and `AccumulationPlanCreate` stays loose on
         *     purpose. `crud` is the internal door, nothing migrates, and a plan already
         *     saved without either end stays readable through the GET rather than
         *     becoming a row the app refuses to show. What it cannot do is run: see
         *     `pac.execute_due`, which skips a source-less plan with the reason instead
         *     of spending money it cannot take from anywhere.
         */
        AccumulationPlanWrite: {
            /**
             * Amount
             * @description Amount contributed per occurrence
             */
            amount: number;
            /**
             * Currency
             * @description Currency the contribution is paid in: the source account's cash, e.g. EUR
             */
            currency: string;
            /**
             * End Date
             * @description Last contribution (optional)
             */
            end_date?: string | null;
            /**
             * Execution
             * @description How the broker fills the order: whole_units (floor(amount/price), remainder stays in cash — default) | fractional (exactly `amount`)
             */
            execution?: string | null;
            /**
             * Frequency
             * @description monthly | quarterly | semiannual | annual
             */
            frequency?: string | null;
            /**
             * Name
             * @description Plan name (e.g. 'PAC All-World')
             */
            name: string;
            /**
             * Notes
             * @description Free-form notes
             */
            notes?: string | null;
            /**
             * Source Institution Id
             * @description The account whose cash funds the plan. Required: a plan that does not say where the money comes from cannot take it from anywhere, and every buy it writes spends money no account loses.
             */
            source_institution_id: number;
            /**
             * Start Date
             * @description First contribution
             */
            start_date?: string | null;
            /**
             * Targets
             * @description Instruments this plan buys, with their weights
             */
            targets?: components["schemas"]["PlanTargetWrite"][];
        };
        /**
         * AllocationSlice
         * @description One country/sector with its weight (percent, 0-100).
         */
        AllocationSlice: {
            /** Name */
            name: string;
            /** Pct */
            pct: number;
        };
        /**
         * ArrivedPosition
         * @description A row a situation declared that the app was not expecting.
         *
         *     Only reported for a situation that ALSO failed to account for something,
         *     because value arriving breaks no rule on its own — a reader may declare
         *     whatever they hold. Beside what went missing it is usually the same money
         *     described better, and the two numbers together are what tell a
         *     reformulation from a loss.
         */
        ArrivedPosition: {
            /** Appeared On */
            appeared_on: string;
            /** Asset Name */
            asset_name: string;
            /** Institution */
            institution: string | null;
            /** Institution Id */
            institution_id: number | null;
            /** Symbol */
            symbol: string | null;
            /** Value */
            value: number;
        };
        /**
         * AssetClassSlice
         * @description One slice of the financial allocation (by asset class).
         */
        AssetClassSlice: {
            /** Asset Class */
            asset_class: string;
            /** Value */
            value: number;
        };
        /**
         * BaseCurrencySetting
         * @description The currency every total is shown in.
         */
        BaseCurrencySetting: {
            /**
             * Base Currency
             * @description An ISO code the ECB reference-rate feed quotes, e.g. EUR, USD
             */
            base_currency: string;
        };
        /**
         * BaseCurrencySettingRead
         * @description The base, and the currencies it may be changed to.
         */
        BaseCurrencySettingRead: {
            /**
             * Available
             * @description The currencies the ECB feed quotes today, which are the only ones a total can be converted into. Just the current base when the feed has never been reached.
             */
            available: string[];
            /**
             * Base Currency
             * @description An ISO code the ECB reference-rate feed quotes, e.g. EUR, USD
             */
            base_currency: string;
        };
        /**
         * CashAnchorCreate
         * @description Payload to create an anchor. institution_id comes from the URL.
         */
        CashAnchorCreate: {
            /**
             * Amount
             * @description Actual cash at that date
             */
            amount: number;
            /**
             * Currency
             * @description Currency, e.g. EUR
             */
            currency: string;
            /**
             * Date
             * Format: date
             * @description Balance date (YYYY-MM-DD)
             */
            date: string;
            /**
             * Note
             * @description Free-form notes
             */
            note?: string | null;
        };
        /**
         * CashAnchorRead
         * @description A stored anchor as returned by the API.
         */
        CashAnchorRead: {
            /**
             * Amount
             * @description Actual cash at that date
             */
            amount: number;
            /** Created At */
            created_at: string;
            /**
             * Currency
             * @description Currency, e.g. EUR
             */
            currency: string;
            /**
             * Date
             * Format: date
             * @description Balance date (YYYY-MM-DD)
             */
            date: string;
            /** Id */
            id: number;
            /** Institution Id */
            institution_id: number;
            /**
             * Note
             * @description Free-form notes
             */
            note: string | null;
        };
        /**
         * CashFlowSummary
         * @description The income and expenses IN FORCE today as a monthly run-rate, one-offs
         *     excluded, and the flows those figures leave out
         *     (`analytics.compute_flows_in_force`, the analysis's own computation).
         */
        CashFlowSummary: {
            /** Active Income */
            active_income: number;
            /**
             * Base Currency
             * @description The currency this payload's computed amounts are in — the database's base, as the figures were converted. Figures a row states itself (an anchor, a transaction, a valuation) keep their own `currency`.
             */
            base_currency: string;
            /** Discretionary Expenses */
            discretionary_expenses: number;
            /**
             * Ended
             * @description Ended before today: no longer counted
             */
            ended: components["schemas"]["FlowNotCounted"][];
            /** Essential Expenses */
            essential_expenses: number;
            /** Expenses In Force */
            expenses_in_force: number;
            /**
             * Incomes In Force
             * @description So 'none in force' can be told from a sum of zero
             */
            incomes_in_force: number;
            /** Monthly Expenses */
            monthly_expenses: number;
            /** Monthly Income */
            monthly_income: number;
            /** Monthly Net */
            monthly_net: number;
            /**
             * On
             * Format: date
             * @description The day the flows are in force on: today
             */
            on: string;
            /** Passive Income */
            passive_income: number;
            /** Savings Rate */
            savings_rate: number | null;
            /**
             * Scheduled
             * @description First payment after today: not counted until then
             */
            scheduled: components["schemas"]["FlowNotCounted"][];
            /**
             * Undated
             * @description Flows with no start date, counted as in force: nothing says they have not started
             */
            undated: number;
        };
        /**
         * CashPosition
         * @description Projected cash for one institution at `as_of`, with its breakdown:
         *     projected = anchor_amount + income − expenses + transfers_in − transfers_out
         *     − buys (events counted only AFTER the anchor date, up to as_of).
         */
        CashPosition: {
            /** Anchor Amount */
            anchor_amount: number;
            /** Anchor Date */
            anchor_date: string | null;
            /**
             * As Of
             * Format: date
             */
            as_of: string;
            /**
             * Base Currency
             * @description The currency this payload's computed amounts are in — the database's base, as the figures were converted. Figures a row states itself (an anchor, a transaction, a valuation) keep their own `currency`.
             */
            base_currency: string;
            /**
             * Buys
             * @description Investment purchases paid by this institution's cash
             */
            buys: number;
            /** Expenses */
            expenses: number;
            /** Income */
            income: number;
            /** Institution Id */
            institution_id: number;
            /** Institution Name */
            institution_name: string;
            /** Projected */
            projected: number;
            /**
             * Sells
             * @description Sale proceeds and dividends credited to this institution
             */
            sells: number;
            /** Transfers In */
            transfers_in: number;
            /** Transfers Out */
            transfers_out: number;
        };
        /**
         * CatalogueStatus
         * @description What the local registry holds and how old it is. Shown, not assumed: a
         *     picker searching a catalogue downloaded months ago is a different tool from
         *     one searching today's.
         *
         *     `state` is where the app's own download stands: "downloading"; "failed",
         *     tried again at a page load from `retry_after` on; "ready"; or
         *     "not_started", an empty registry nobody has asked about since the server
         *     started (a reload asks).
         */
        CatalogueStatus: {
            /** Fetched At */
            fetched_at: string | null;
            /** Retry After */
            retry_after: string | null;
            /**
             * Rows
             * @default 0
             */
            rows: number;
            /** Source */
            source: string | null;
            /**
             * State
             * @default ready
             * @enum {string}
             */
            state: "ready" | "downloading" | "failed" | "not_started";
        };
        /**
         * CatchUpResult
         * @description Outcome of a catch-up run: transactions created for every elapsed,
         *     still-unrecorded PAC occurrence and dividend ex-date, plus what was
         *     skipped (retried on the next run).
         */
        CatchUpResult: {
            /** Created */
            created: components["schemas"]["TransactionRead"][];
            /** Skipped */
            skipped: components["schemas"]["CatchUpSkip"][];
        };
        /**
         * CatchUpSkip
         * @description One catch-up item that could NOT be executed, and why. `label` names
         *     the source (a PAC plan or a dividend-paying symbol).
         */
        CatchUpSkip: {
            /** Label */
            label: string;
            /** Occurrence */
            occurrence: string | null;
            /** Reason */
            reason: string;
        };
        /**
         * ChainRunRead
         * @description A chain run: the final verdict plus every step, so the reasoning stays
         *     inspectable.
         */
        ChainRunRead: {
            /** Created At */
            created_at: string;
            /** Id */
            id: number;
            /** Steps */
            steps: components["schemas"]["ChainStepRead"][];
            /** Verdict */
            verdict: string | null;
        };
        /**
         * ChainRunSummary
         * @description One run as a LIST reads it: when it ran, how deep it went, and whether
         *     the confidant actually argued.
         *
         *     No text. The verdict is a document and the steps are four more of them, and
         *     a list that carried them would download every word four models ever wrote
         *     so the reader could choose a date.
         *
         *     `challenge` is the whole point of the shape. The chain's value is that the
         *     confidant is adversarial, and a mandate that never bites is an expensive
         *     way to agree with yourself — so whether it bit has to be readable from
         *     outside the run, and across runs it is a count. It is the confidant's own
         *     `VERDICT:` marker and not an inference from how many steps there were: the
         *     two can disagree, and the marker is the one that says what was meant.
         *
         *     'unstated' is a third answer and not a quiet 'fits'. It means no turn of
         *     that run ended on a marker this code recognises, so the run says nothing
         *     about the mandate either way and must not be counted as if it did.
         */
        ChainRunSummary: {
            /**
             * Challenge
             * @description The confidant's own VERDICT marker for the run: whether it challenged something that mattered, waved the findings through, or ended on no marker at all
             * @enum {string}
             */
            challenge: "contested" | "fits" | "unstated";
            /** Created At */
            created_at: string;
            /** Id */
            id: number;
            /**
             * Revisions
             * @description How many times the analyst was asked to answer the challenge — the depth the argument actually bought
             */
            revisions: number;
            /**
             * Step Count
             * @description How many turns the run took, 3 to 7
             */
            step_count: number;
        };
        /**
         * ChainStepRead
         * @description One role's turn in a chain run, with the model that produced it.
         */
        ChainStepRead: {
            /** Cost */
            cost: number | null;
            /** Duration Ms */
            duration_ms: number | null;
            /** Model */
            model: string | null;
            /** Output */
            output: string;
            /** Role */
            role: string;
            /** Step No */
            step_no: number;
            /** Title */
            title: string;
        };
        /**
         * ChatCard
         * @description A card has been proposed, and the turn is about to end on it.
         *
         *     It carries the block itself rather than repeating its fields, so the panel
         *     renders one shape whether the card just arrived or was read back from the
         *     history — and so the two cannot come to disagree, which nine fields
         *     written out twice eventually do.
         *
         *     The turn ENDS here, and ends on `done`. SSE is one-directional and the
         *     confirmation is a new request, so holding the stream open while a person
         *     decides would leave a call billing to nobody — and would need a fourth
         *     ending called "waiting for you", which `cut` would then be indistinguishable
         *     from. A closed browser leaves nothing pending: the card is a stored block,
         *     so it is still there when the reader comes back, and so is the fact that
         *     they never answered it.
         */
        ChatCard: {
            card: components["schemas"]["ChatCardBlock"];
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            kind: "card";
        };
        /**
         * ChatCardBlock
         * @description A write the model PROPOSED, and what became of it.
         *
         *     Nothing has happened when this is written. The model never calls `crud`;
         *     it drafts a change, this is how the change is shown, and the write runs
         *     from the normal path only after the reader confirms it — same `crud`, same
         *     unit of work, same contract the form goes through. The chat does not get a
         *     service door the form does not have, and a wrong field is corrected on the
         *     card rather than in the database.
         *
         *     `outcome` and `result` are why the block is rewritten in place instead of
         *     a second block being appended: a history that shows what was proposed and
         *     not what happened is a "done!" with no receipt, and a rejected card has to
         *     stay visible as a rejected card. Both states are on record.
         *
         *     `card_id` exists because a block otherwise has no address — the JSON list
         *     has no key and its index is not promised to be stable — and the endpoint
         *     that settles this one has to be able to name it.
         *
         *     `call_id` is the id the MODEL's tool call carried, kept so the exchange can
         *     be replayed to it: the API pairs an assistant turn's `tool_calls` with the
         *     `tool` turns that answer them by exactly this string, and a conversation
         *     missing one is refused.
         *
         *     `confirmation` is the rule from the domain and not a UI preference, and it
         *     is about REVERSIBILITY. An event — a transaction, a dated valuation — is
         *     verifiable and undone by deleting it, so it gets a light confirmation.
         *     Anything that OVERWRITES gets `diff` and the field-by-field of what would
         *     be replaced: a snapshot, because editing it rewrites what that day said and
         *     every projection anchored after it moves, and equally a questionnaire
         *     answer, which is not kept in history, and after this says something else
         *     and carries another day.
         *
         *     `fingerprint` is what the proposal depended on when it was made, so the
         *     confirmation can tell whether the ground moved under it. See
         *     `tools.Proposal`.
         */
        ChatCardBlock: {
            /** Arguments */
            arguments?: {
                [key: string]: unknown;
            };
            /** Call Id */
            call_id: string;
            /** Card Id */
            card_id: string;
            /**
             * Confirmation
             * @default light
             * @enum {string}
             */
            confirmation?: "light" | "diff";
            /**
             * Consequence
             * @description What confirming this costs that the diff does not show, in the proposing tool's own words. Only the tool knows: editing a snapshot moves every figure anchored after it, while replacing a questionnaire answer moves nothing and simply loses the old one. Empty falls back to the one thing true of every diff card — that it replaces what is on record and the old value does not come back.
             * @default
             */
            consequence?: string;
            /** Diff */
            diff?: components["schemas"]["ChatCardChange"][];
            /**
             * Done
             * @description What a confirmed card says it is now: 'Recorded', 'Added to your watchlist'
             * @default
             */
            done?: string;
            /**
             * Fields
             * @description The proposal's arguments in the reader's words, the absent ones left out
             */
            fields?: components["schemas"]["ChatCardField"][];
            /**
             * Fingerprint
             * @default
             */
            fingerprint?: string;
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            kind: "card";
            /**
             * Outcome
             * @default pending
             * @enum {string}
             */
            outcome?: "pending" | "confirmed" | "rejected";
            /**
             * Receipt
             * @description What a confirmed card wrote, in the reader's words; empty until then
             */
            receipt?: components["schemas"]["ChatCardField"][];
            /**
             * Result
             * @description What the write produced, once it ran — the fields as the tool returned them, not a sentence about them. Two readers want this and they want it in the same shape: the model, which is handed it back as the answer to its call, and the card, which shows it under the diff in the same field-by-field form the diff used. Rendered to a string here it would have to be parsed back for one of them.
             */
            result?: {
                [key: string]: unknown;
            } | null;
            /** Title */
            title: string;
            /** Tool */
            tool: string;
            /**
             * Verb
             * @description What pressing the accept button DOES, in the proposing tool's own words — 'Add to watchlist' rather than 'Confirm'. Empty means Confirm, which is right for everything that writes to the reader's records. It is the tool's word for the same reason `consequence` is: a suggestion changes nothing about their money, and 'Confirm' over a card naming a security reads as approval of a purchase that is not being proposed.
             * @default
             */
            verb?: string;
        };
        /**
         * ChatCardChange
         * @description One line of a card's diff: what a field says now, and what it would say.
         *
         *     Both sides are TEXT and not numbers, because a diff is read and not
         *     computed with. `now` is null where the record says nothing yet, which is a
         *     different thing from a zero and has to look different.
         */
        ChatCardChange: {
            /** Field */
            field: string;
            /** Now */
            now?: string | null;
            /** Proposed */
            proposed?: string | null;
        };
        /**
         * ChatCardDecision
         * @description The reader's answer to one card.
         *
         *     Deliberately not named `...Create`: it creates nothing, and the contract
         *     test parametrizes every schema whose name ends that way. `ChatRequest` set
         *     that precedent for a chat body already.
         *
         *     Only a decision, and no corrected arguments. Deferred once already,
         *     against the fake tool, and now decided
         *     against the three real ones, so it is a decision rather than a gap.
         *
         *     A card's `arguments` are an untyped dict, because one block type carries
         *     every tool's proposal. An editor over that can only guess its widget from
         *     the runtime type of the JSON value, and every field that is worth
         *     correcting is exactly where that guess fails: a date is a string, a
         *     currency is a string, an asset class is a string with six legal values, and
         *     an institution is a name that has to resolve against a row. So an editable
         *     card either asks the reader to hand-type what the tool exists to resolve
         *     for them, or the card has to carry per-field metadata — which is the
         *     argument schema, declared a second time, in the one place `tools.py` opens
         *     by refusing to declare anything twice.
         *
         *     The correction that does work today costs one round trip and has a single
         *     author: "no, 450" and the model draws a fresh card. When editing is built
         *     it should come from the argument model's own JSON schema, generated where
         *     the tool schema is generated, and that is a design and not a field.
         */
        ChatCardDecision: {
            /**
             * Decision
             * @enum {string}
             */
            decision: "confirm" | "reject";
            /**
             * Model
             * @description OpenRouter slug for the follow-up; empty means the chat default
             */
            model?: string | null;
        };
        /**
         * ChatCardField
         * @description One line of a card as the reader reads it: a label in their words and a
         *     value, never a schema name, a row id or a timestamp (brief AJ: the
         *     reader's cards said "based_on", "symbol null", a row's id, and an ISO
         *     timestamp under "added_at"). `kind` says how the panel writes
         *     the value in the reader's language: a day ("date", YYYY-MM-DD), a number,
         *     or an amount in `currency`.
         */
        ChatCardField: {
            /** Currency */
            currency?: string | null;
            /**
             * Kind
             * @default text
             * @enum {string}
             */
            kind?: "text" | "date" | "number" | "amount";
            /** Label */
            label: string;
            /** Value */
            value: string;
        };
        /**
         * ChatConversationDetail
         * @description The conversation with every turn, oldest first.
         */
        ChatConversationDetail: {
            /** Created At */
            created_at: string;
            /** Id */
            id: number;
            /** Messages */
            messages: components["schemas"]["ChatMessageRead"][];
            /** Title */
            title: string | null;
            /** Updated At */
            updated_at: string;
        };
        /**
         * ChatConversationRead
         * @description A conversation as the history list shows it: its first question as the
         *     title, and when it was last spoken to.
         */
        ChatConversationRead: {
            /** Created At */
            created_at: string;
            /** Id */
            id: number;
            /** Title */
            title: string | null;
            /** Updated At */
            updated_at: string;
        };
        /**
         * ChatDecided
         * @description A card has been decided, and this is the card as it is now stored.
         *
         *     Sent the moment the decision is on record: right after `start` for every
         *     card but the analyzer's, whose decision is stored when its run is, after
         *     its steps. The panel swaps the card it shows for this one there and then,
         *     so the card reads as decided whatever the turn that follows does. Until
         *     brief AJ the panel coloured it only once that turn had ended well: the
         *     reader's second confirmation, on 2026-10-08, was stored, its follow-up
         *     failed, and the card kept its buttons; pressing again was refused as a
         *     decision already taken. The block itself, for the reason `ChatCard`
         *     carries one: one shape, whether it arrived now or is read back later.
         */
        ChatDecided: {
            card: components["schemas"]["ChatCardBlock"];
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            kind: "decided";
        };
        /**
         * ChatDelta
         * @description A piece of the answer, in order. Concatenate them.
         */
        ChatDelta: {
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            kind: "delta";
            /** Text */
            text: string;
        };
        /**
         * ChatDone
         * @description The answer is complete and stored. Its ABSENCE is the signal: a stream
         *     that ends without this event broke off, and the client must say so rather
         *     than show a truncated answer as though it were the whole one.
         */
        ChatDone: {
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            kind: "done";
            /** Message Id */
            message_id: number;
            /** Model */
            model: string;
        };
        /**
         * ChatError
         * @description The answer cannot continue, and why. Sent in place of `done`.
         */
        ChatError: {
            /** Detail */
            detail: string;
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            kind: "error";
        };
        /**
         * ChatMessageRead
         * @description One stored turn. `status` is how an assistant turn ENDED — done, error
         *     (with `detail`), or cut, the connection closed before it finished — and
         *     null on a user turn.
         */
        ChatMessageRead: {
            /** Blocks */
            blocks: (components["schemas"]["ChatTextBlock"] | components["schemas"]["ChatThoughtBlock"] | components["schemas"]["ChatPageBlock"] | components["schemas"]["ChatToolBlock"] | components["schemas"]["ChatSourcesBlock"] | components["schemas"]["ChatCardBlock"])[];
            /** Created At */
            created_at: string;
            /** Detail */
            detail: string | null;
            /** Id */
            id: number;
            /** Model */
            model: string | null;
            /** Role */
            role: string;
            /** Seq */
            seq: number;
            /** Status */
            status: string | null;
        };
        /**
         * ChatModel
         * @description One entry of the model dropdown.
         */
        ChatModel: {
            /**
             * Note
             * @description What is known about it, with the date it was checked
             */
            note: string | null;
            /** Slug */
            slug: string;
        };
        /**
         * ChatModelsRead
         * @description What the dropdown offers, and which of them answers when nothing is picked.
         */
        ChatModelsRead: {
            /** Default */
            default: string;
            /** Models */
            models: components["schemas"]["ChatModel"][];
        };
        /**
         * ChatPageAccount
         * @description One institution's page: its cash register and its situations.
         */
        ChatPageAccount: {
            /** Institution Id */
            institution_id: number;
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            kind: "account";
        };
        /**
         * ChatPageAnalyses
         * @description The list of every analysis run.
         */
        ChatPageAnalyses: {
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            kind: "analyses";
        };
        /**
         * ChatPageAnalysis
         * @description One analysis run, open in the main column.
         */
        ChatPageAnalysis: {
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            kind: "analysis";
            /** Run Id */
            run_id: number;
        };
        /**
         * ChatPageBlock
         * @description Where in the app the reader was when they asked — kept on the question,
         *     before its words.
         *
         *     A NAME and not an id, fixed at the moment of asking: "Records → Wealth →
         *     Broker B". The reader moves between messages, so where they are now says
         *     nothing about where an earlier question was asked, and a conversation that
         *     renamed its past when an account was renamed would be rewriting what was
         *     said. The same reason a sum fixed on a day is never restated.
         *
         *     It is the APP's sentence, never the reader's, which is why it is a block of
         *     its own rather than a line pasted into their text. See `app/screen.py`.
         */
        ChatPageBlock: {
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            kind: "page";
            /** Label */
            label: string;
        };
        /** ChatPageDashboard */
        ChatPageDashboard: {
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            kind: "dashboard";
        };
        /**
         * ChatPageDebt
         * @description One debt's page: its outstanding balance over time.
         */
        ChatPageDebt: {
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            kind: "debt";
            /** Liability Id */
            liability_id: number;
        };
        /** ChatPagePortfolio */
        ChatPagePortfolio: {
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            kind: "portfolio";
        };
        /** ChatPageProfile */
        ChatPageProfile: {
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            kind: "profile";
        };
        /**
         * ChatPageRealAsset
         * @description One real asset's page: its dated valuations.
         */
        ChatPageRealAsset: {
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            kind: "real_asset";
            /** Real Asset Id */
            real_asset_id: number;
        };
        /**
         * ChatPageRecords
         * @description A sub-page of Records with nothing opened inside it.
         */
        ChatPageRecords: {
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            kind: "records";
            /**
             * Section
             * @enum {string}
             */
            section: "wealth" | "real" | "debts" | "cash";
        };
        /**
         * ChatPageSituation
         * @description One dated situation, opened from its account's page.
         */
        ChatPageSituation: {
            /** Institution Id */
            institution_id: number;
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            kind: "situation";
            /** Snapshot Id */
            snapshot_id: number;
        };
        /**
         * ChatRequest
         * @description One more question in a conversation.
         *
         *     The server holds the conversation, so the client sends only the new
         *     question and which conversation it belongs to — none, and a new one is
         *     opened for it. The financial context is rebuilt from the database on each
         *     request, so what the model reads is never older than the question.
         */
        ChatRequest: {
            /** Content */
            content: string;
            /**
             * Conversation Id
             * @description Continue this conversation; null opens a new one
             */
            conversation_id?: number | null;
            /**
             * Model
             * @description OpenRouter slug; empty means the configured chat default
             */
            model?: string | null;
            /**
             * Page
             * @description The page on screen when this was sent. A hint about what 'this' refers to, never a narrowing of the question; null says nothing
             */
            page?: (components["schemas"]["ChatPageDashboard"] | components["schemas"]["ChatPagePortfolio"] | components["schemas"]["ChatPageProfile"] | components["schemas"]["ChatPageRecords"] | components["schemas"]["ChatPageAccount"] | components["schemas"]["ChatPageSituation"] | components["schemas"]["ChatPageRealAsset"] | components["schemas"]["ChatPageDebt"] | components["schemas"]["ChatPageAnalyses"] | components["schemas"]["ChatPageAnalysis"]) | null;
        };
        /**
         * ChatSource
         * @description A page a web search found, as it arrives.
         *
         *     Sent when OpenRouter hands it over: once the search has run, which is
         *     before the words written from it, or at the end of a round that ended on
         *     the app's own tools. The panel lists it where it arrived, as the stored
         *     `ChatSourcesBlock` will when the conversation is read back.
         */
        ChatSource: {
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            kind: "source";
            /** Title */
            title: string;
            /** Url */
            url: string;
        };
        /**
         * ChatSourcesBlock
         * @description The pages a web search found, kept where the search ran.
         *
         *     Provenance, for the reason a `ChatToolBlock` is kept: an answer that says
         *     "Vanguard gives 0.03%" got that from somewhere, and the reader is owed the
         *     page. These are what the search RETURNED (OpenRouter's search on Exa hands
         *     back every page it found, five a search), so they are the pages the model
         *     was given to read, not a claim about which of them it used; the sentence
         *     that uses one carries its link. A page found twice in a turn is listed
         *     once. Never sent back to the model with a later turn: past turns travel as
         *     their words, and a link the model wrote travels inside them.
         */
        ChatSourcesBlock: {
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            kind: "sources";
            /** Pages */
            pages: components["schemas"]["ChatWebPage"][];
        };
        /**
         * ChatStart
         * @description The first frame: which conversation this turn landed in — the id a new
         *     conversation was given — and the stored id of the question.
         *
         *     Null where there was no question. Answering a card resumes a conversation
         *     without anybody asking anything: the reader pressed confirm, and inventing
         *     a user turn to hang the id on would put a sentence in their mouth that
         *     they never wrote.
         *
         *     `page_label` is where the question was stored as asked from, as the server
         *     resolved it — a page gone since has already climbed a level. It arrives
         *     before the answer so the panel can print it under the question while the
         *     answer is still being written, from the one authority on it rather than
         *     from a guess of its own.
         */
        ChatStart: {
            /** Conversation Id */
            conversation_id: number;
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            kind: "start";
            /** Page Label */
            page_label?: string | null;
            /** User Message Id */
            user_message_id?: number | null;
        };
        /**
         * ChatStep
         * @description A long tool has finished one of its steps, and is going on.
         *
         *     Sent while it runs, and never stored. Its job is `ChatTool`'s job said more
         *     than once: to be what the silence IS. The analyzer is three to six model
         *     calls and a minute of them, and the page it used to live on refused to fake
         *     a progress bar for exactly the right reason — `run_chain` wrote nothing
         *     until all of it had finished, so "step 2 of 4" would have been invented.
         *     Now each finished step is a fact the orchestrator was told, so it can be
         *     said without inventing anything.
         *
         *     Nothing here is a record. What is persisted is the run itself, whole, at
         *     the end — and the card that proposed it becomes the receipt. A second copy
         *     of "the analyst finished at 12s" inside the message blocks would be a third
         *     place the same run lives.
         */
        ChatStep: {
            /** Duration Ms */
            duration_ms: number;
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            kind: "step";
            /** Label */
            label: string;
            /** Step No */
            step_no: number;
            /** Tool */
            tool: string;
        };
        /**
         * ChatTextBlock
         * @description A run of text in a message.
         */
        ChatTextBlock: {
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            kind: "text";
            /** Text */
            text: string;
        };
        /**
         * ChatThought
         * @description A piece of the model's reasoning, in order, before the answer starts.
         *     Shown folded and quiet: it is how the wait is spent, not the answer.
         */
        ChatThought: {
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            kind: "thought";
            /** Text */
            text: string;
        };
        /**
         * ChatThoughtBlock
         * @description The model's reasoning before it answered — kept, folded, so the reader
         *     can see how the answer was reached, and never sent back to the model.
         */
        ChatThoughtBlock: {
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            kind: "thought";
            /** Text */
            text: string;
        };
        /**
         * ChatTool
         * @description A tool has been asked for and is running.
         *
         *     Sent BEFORE the tool runs, not after, because its whole job is to say what
         *     the silence is. The look-through reads a cache in milliseconds and walks
         *     four fund issuers when the cache is cold, and the difference between those
         *     two is the difference between a pause and a minute — the same argument
         *     that put the model's own thinking on the wire rather than leaving a
         *     spinner. How it WENT is not here: it is in the stored `ChatToolBlock`, and
         *     in the answer the model writes next.
         *
         *     Except a failure, since brief AG (2026-10-06). The loop answers a call
         *     before it sends this, so a refusal is known by then, and `detail` carries
         *     its reason, as the stored block keeps it: a suggestion past the third in
         *     one answer, or one Yahoo could not vouch for, arrives in a round that ends
         *     on the cards it did draw, where the model never gets to say why it is
         *     missing. Null when nothing failed, which is not a claim that anything
         *     succeeded.
         */
        ChatTool: {
            /** Detail */
            detail?: string | null;
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            kind: "tool";
            /** Name */
            name: string;
        };
        /**
         * ChatToolBlock
         * @description A tool the model consulted while writing this answer, kept in the place
         *     it was consulted.
         *
         *     It is here for provenance, which is the same reason every figure on this
         *     reader's screen carries where it came from. An answer that says "counting
         *     inside your funds, NVIDIA is 4.2% of the portfolio" got that from
         *     somewhere, and a stored answer that does not say so is the one number on
         *     the screen that cannot be traced. `ok` is false when the tool refused or
         *     broke, and `detail` says why: an answer written after a tool failed was
         *     written with less than it asked for, and the reader is owed that.
         */
        ChatToolBlock: {
            /** Detail */
            detail?: string | null;
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            kind: "tool";
            /** Name */
            name: string;
            /** Ok */
            ok: boolean;
        };
        /**
         * ChatWebPage
         * @description One page a web search found: its address and its title. An http or https
         *     address only, checked where it entered (`advisor._page`), because it is
         *     shown as a link the reader can press.
         */
        ChatWebPage: {
            /** Title */
            title: string;
            /** Url */
            url: string;
        };
        /**
         * CompositionRow
         * @description Look-through status of one portfolio position: what it resolved to,
         *     which source decomposed it, or why it stayed whole.
         */
        CompositionRow: {
            /** Asset Class */
            asset_class: string | null;
            /** Asset Name */
            asset_name: string;
            /** Decomposed */
            decomposed: boolean;
            /** Error */
            error: string | null;
            /** Fetched At */
            fetched_at: string | null;
            /** Holdings Count */
            holdings_count: number | null;
            /** Isin */
            isin: string | null;
            /** Resolved Name */
            resolved_name: string | null;
            /**
             * Source
             * @description justetf | mstarpy | yfinance
             */
            source: string | null;
            /** Symbol */
            symbol: string | null;
            /** Weight Pct */
            weight_pct: number;
        };
        /**
         * DashboardAllocation
         * @description Top-level financial-vs-real split, with per-class / per-category detail.
         */
        DashboardAllocation: {
            /**
             * Base Currency
             * @description The currency this payload's computed amounts are in — the database's base, as the figures were converted. Figures a row states itself (an anchor, a transaction, a valuation) keep their own `currency`.
             */
            base_currency: string;
            /** By Asset Class */
            by_asset_class: components["schemas"]["AssetClassSlice"][];
            /** By Real Category */
            by_real_category: components["schemas"]["RealCategorySlice"][];
            /** Financial Total */
            financial_total: number;
            /** Real Total */
            real_total: number;
        };
        /**
         * DashboardSummary
         * @description Net worth = financial + real − liabilities, plus the splits and counts.
         *
         *     financial_total = investments_total (snapshots, ex-cash) + cash_total
         *     (the live cash register projected to today). liabilities_total = sum of
         *     the latest outstanding balance of each debt.
         */
        DashboardSummary: {
            /** As Of */
            as_of: string | null;
            /**
             * Base Currency
             * @description The currency this payload's computed amounts are in — the database's base, as the figures were converted. Figures a row states itself (an anchor, a transaction, a valuation) keep their own `currency`.
             */
            base_currency: string;
            /** Cash Total */
            cash_total: number;
            /**
             * Declared Instead
             * @description What those same situations declared that the app was not expecting. Three summary rows replaced by twenty-one positions is a portfolio described better, not their value lost, and naming only the first half cannot tell the reader which it is.
             */
            declared_instead: components["schemas"]["ArrivedPosition"][];
            /** Financial Total */
            financial_total: number;
            /** Institutions */
            institutions: number;
            /**
             * Investments At Book
             * @description How much of it is carried over from the last photograph instead
             * @default 0
             */
            investments_at_book: number;
            /**
             * Investments At Market
             * @description How much of the investment total the market actually priced
             * @default 0
             */
            investments_at_market: number;
            /** Investments Total */
            investments_total: number;
            /** Liabilities */
            liabilities: number;
            /** Liabilities Total */
            liabilities_total: number;
            /** Net Worth */
            net_worth: number;
            /** Real Assets */
            real_assets: number;
            /** Real Total */
            real_total: number;
            /**
             * Unconverted
             * @description Amounts that entered these totals without being converted, because no rate is known for the currency they are written in — said here instead of passing in silence. Each entry is a sum over ROWS and not the amount any figure above is wrong by; `UnconvertedAmount` says why, with the measured cases in both directions.
             */
            unconverted: components["schemas"]["UnconvertedAmount"][];
            /**
             * Unresolved Omissions
             * @description Value that left the totals because a newer photograph did not mention it. Selling is an assertion with a date and proceeds; forgetting is the absence of one, and the app must not let the difference pass in silence.
             */
            unresolved_omissions: components["schemas"]["OmittedPosition"][];
        };
        /**
         * ExpenseCreate
         * @description Payload to create an expense.
         */
        ExpenseCreate: {
            /**
             * Amount
             * @description Amount per occurrence
             */
            amount: number;
            /**
             * Category
             * @description housing | food | transport | utilities | health | insurance | debt | leisure | education | other
             */
            category?: string | null;
            /**
             * Currency
             * @description Currency, e.g. EUR
             */
            currency: string;
            /**
             * End Date
             * @description Last occurrence (optional; open-ended if null)
             */
            end_date?: string | null;
            /**
             * Frequency
             * @description monthly | quarterly | semiannual | annual | one_off
             */
            frequency?: string | null;
            /**
             * Institution Id
             * @description Institution whose cash this expense draws from
             */
            institution_id?: number | null;
            /**
             * Name
             * @description Expense name (e.g. 'Rent', 'Groceries')
             */
            name: string;
            /**
             * Nature
             * @description essential | discretionary
             */
            nature?: string | null;
            /**
             * Notes
             * @description Free-form notes
             */
            notes?: string | null;
            /**
             * Start Date
             * @description First occurrence / one-off date (YYYY-MM-DD)
             */
            start_date?: string | null;
        };
        /**
         * ExpenseRead
         * @description Representation of an expense returned by the API.
         */
        ExpenseRead: {
            /**
             * Amount
             * @description Amount per occurrence
             */
            amount: number;
            /**
             * Category
             * @description housing | food | transport | utilities | health | insurance | debt | leisure | education | other
             */
            category: string | null;
            /** Created At */
            created_at: string;
            /**
             * Currency
             * @description Currency, e.g. EUR
             */
            currency: string;
            /**
             * End Date
             * @description Last occurrence (optional; open-ended if null)
             */
            end_date: string | null;
            /**
             * Frequency
             * @description monthly | quarterly | semiannual | annual | one_off
             */
            frequency: string | null;
            /** Id */
            id: number;
            /**
             * Institution Id
             * @description Institution whose cash this expense draws from
             */
            institution_id: number | null;
            /**
             * Name
             * @description Expense name (e.g. 'Rent', 'Groceries')
             */
            name: string;
            /**
             * Nature
             * @description essential | discretionary
             */
            nature: string | null;
            /**
             * Notes
             * @description Free-form notes
             */
            notes: string | null;
            /**
             * Start Date
             * @description First occurrence / one-off date (YYYY-MM-DD)
             */
            start_date: string | null;
        };
        /**
         * FlowNotCounted
         * @description An income or an expense the monthly figures leave out, with the dates
         *     that say why: its first payment is after today, or it has ended. The Cash
         *     flow page marks its own row by `side` and `id`.
         */
        FlowNotCounted: {
            /** End Date */
            end_date: string | null;
            /** Frequency */
            frequency: string | null;
            /** Id */
            id: number;
            /** Name */
            name: string;
            /**
             * Side
             * @enum {string}
             */
            side: "income" | "expense";
            /** Start Date */
            start_date: string | null;
        };
        /**
         * FxRateRead
         * @description One ECB reference rate: units of `currency` per 1 `base` on `as_of`.
         */
        FxRateRead: {
            /** As Of */
            as_of: string;
            /** Base */
            base: string;
            /** Currency */
            currency: string;
            /** Fetched At */
            fetched_at: string;
            /** Rate */
            rate: number;
        };
        /**
         * GoalCreate
         * @description Payload to create a goal.
         */
        GoalCreate: {
            /**
             * Currency
             * @description Currency, e.g. EUR
             */
            currency: string;
            /** Current Amount */
            current_amount?: number | null;
            /** Monthly Contribution */
            monthly_contribution?: number | null;
            /** Name */
            name: string;
            /** Notes */
            notes?: string | null;
            /** Target Amount */
            target_amount?: number | null;
            /** Target Date */
            target_date?: string | null;
            /** Type */
            type?: string | null;
        };
        /**
         * GoalRead
         * @description A stored goal as returned by the API.
         */
        GoalRead: {
            /** Created At */
            created_at: string;
            /**
             * Currency
             * @description Currency, e.g. EUR
             */
            currency: string;
            /** Current Amount */
            current_amount: number | null;
            /** Id */
            id: number;
            /** Monthly Contribution */
            monthly_contribution: number | null;
            /** Name */
            name: string;
            /** Notes */
            notes: string | null;
            /** Target Amount */
            target_amount: number | null;
            /** Target Date */
            target_date: string | null;
            /** Type */
            type: string | null;
        };
        /**
         * HoldingCreate
         * @description Payload to create a holding. snapshot_id comes from the URL.
         */
        HoldingCreate: {
            /**
             * Asset Class
             * @description Asset class
             */
            asset_class?: string | null;
            /**
             * Asset Name
             * @description Instrument/asset name
             */
            asset_name: string;
            /**
             * Cost Basis
             * @description What the position cost, in this holding's currency. Null means unknown — and unknown stays unknown rather than being inferred from `value`, which is a valuation, not a price paid.
             */
            cost_basis?: number | null;
            /**
             * Cost Estimated
             * @description True when the cost was derived (e.g. from a reported % return)
             */
            cost_estimated?: boolean | null;
            /**
             * Currency
             * @description Currency, e.g. EUR
             */
            currency: string;
            /**
             * Distribution Policy
             * @description acc | dist (accumulating vs distributing). Left empty, the ticker's own dividend history decides: whatever it pays is recorded, as for a share, which has no policy to choose
             */
            distribution_policy?: string | null;
            /**
             * Isin
             * @description Fund ISIN — what the look-through sources key on
             */
            isin?: string | null;
            /** Quantity */
            quantity?: number | null;
            /**
             * Symbol
             * @description Yahoo ticker used for prices (e.g. VWCE.MI)
             */
            symbol?: string | null;
            /** Unit Price */
            unit_price?: number | null;
            /**
             * Value
             * @description Position value. If absent but quantity and unit_price are set, it is computed.
             */
            value?: number | null;
        };
        /**
         * HoldingRead
         * @description Representation of a holding returned by the API.
         *
         *     Two figures for one row, and they are different facts. `value` is what the
         *     reader TYPED, in `currency`, and it is what the edit form must put back in
         *     the box. `value_base` is what that is worth in the app's base currency, and
         *     it is the only one of the two that may be added to another row.
         */
        HoldingRead: {
            /**
             * Asset Class
             * @description Asset class
             */
            asset_class: string | null;
            /**
             * Asset Name
             * @description Instrument/asset name
             */
            asset_name: string;
            /**
             * Base Currency
             * @description The currency this payload's computed amounts are in — the database's base, as the figures were converted. Figures a row states itself (an anchor, a transaction, a valuation) keep their own `currency`.
             */
            base_currency: string;
            /**
             * Cost Basis
             * @description What the position cost, in this holding's currency. Null means unknown — and unknown stays unknown rather than being inferred from `value`, which is a valuation, not a price paid.
             */
            cost_basis: number | null;
            /**
             * Cost Estimated
             * @description True when the cost was derived (e.g. from a reported % return)
             */
            cost_estimated: boolean | null;
            /**
             * Currency
             * @description Currency, e.g. EUR
             */
            currency: string;
            /**
             * Distribution Policy
             * @description acc | dist (accumulating vs distributing). Left empty, the ticker's own dividend history decides: whatever it pays is recorded, as for a share, which has no policy to choose
             */
            distribution_policy: string | null;
            /** Id */
            id: number;
            /**
             * Isin
             * @description Fund ISIN — what the look-through sources key on
             */
            isin: string | null;
            /**
             * Last Dividend
             * @description The latest ex-date Yahoo lists for this holding's ticker, from the dividend answers the catch-up keeps; null when it was never asked about or lists none. What the line says when no policy is stated and the ticker's own history decides its dividends.
             */
            last_dividend: string | null;
            /** Quantity */
            quantity: number | null;
            /** Snapshot Id */
            snapshot_id: number;
            /**
             * Symbol
             * @description Yahoo ticker used for prices (e.g. VWCE.MI)
             */
            symbol: string | null;
            /** Unit Price */
            unit_price: number | null;
            /**
             * Value
             * @description Position value. If absent but quantity and unit_price are set, it is computed.
             */
            value: number | null;
            /**
             * Value Base
             * @description `value` in `base_currency`, at the ECB rate — by the ticker's listing currency where it has one, by `currency` otherwise. The figure to display and to total; `value` is the one to edit.
             */
            value_base: number;
        };
        /** HTTPValidationError */
        HTTPValidationError: {
            /** Detail */
            detail?: components["schemas"]["ValidationError"][];
        };
        /**
         * IncomeSourceCreate
         * @description Payload to create an income source.
         */
        IncomeSourceCreate: {
            /**
             * Amount
             * @description Amount per occurrence
             */
            amount: number;
            /**
             * Category
             * @description salary | freelance | business | rental | dividends | interest | pension | other
             */
            category?: string | null;
            /**
             * Currency
             * @description Currency, e.g. EUR
             */
            currency: string;
            /**
             * End Date
             * @description Last occurrence (optional; open-ended if null)
             */
            end_date?: string | null;
            /**
             * Frequency
             * @description monthly | quarterly | semiannual | annual | one_off
             */
            frequency?: string | null;
            /**
             * Institution Id
             * @description Institution whose cash this income feeds
             */
            institution_id?: number | null;
            /**
             * Kind
             * @description active | passive
             */
            kind?: string | null;
            /**
             * Name
             * @description Income source name (e.g. 'Salary', 'Apartment rent')
             */
            name: string;
            /**
             * Notes
             * @description Free-form notes
             */
            notes?: string | null;
            /**
             * Start Date
             * @description First occurrence / one-off date (YYYY-MM-DD)
             */
            start_date?: string | null;
        };
        /**
         * IncomeSourceRead
         * @description Representation of an income source returned by the API.
         */
        IncomeSourceRead: {
            /**
             * Amount
             * @description Amount per occurrence
             */
            amount: number;
            /**
             * Category
             * @description salary | freelance | business | rental | dividends | interest | pension | other
             */
            category: string | null;
            /** Created At */
            created_at: string;
            /**
             * Currency
             * @description Currency, e.g. EUR
             */
            currency: string;
            /**
             * End Date
             * @description Last occurrence (optional; open-ended if null)
             */
            end_date: string | null;
            /**
             * Frequency
             * @description monthly | quarterly | semiannual | annual | one_off
             */
            frequency: string | null;
            /** Id */
            id: number;
            /**
             * Institution Id
             * @description Institution whose cash this income feeds
             */
            institution_id: number | null;
            /**
             * Kind
             * @description active | passive
             */
            kind: string | null;
            /**
             * Name
             * @description Income source name (e.g. 'Salary', 'Apartment rent')
             */
            name: string;
            /**
             * Notes
             * @description Free-form notes
             */
            notes: string | null;
            /**
             * Start Date
             * @description First occurrence / one-off date (YYYY-MM-DD)
             */
            start_date: string | null;
        };
        /**
         * InstitutionCreate
         * @description Payload to create an institution (POST).
         */
        InstitutionCreate: {
            /**
             * Name
             * @description Institution name
             */
            name: string;
            /**
             * Notes
             * @description Free-form notes
             */
            notes?: string | null;
            /**
             * Type
             * @description Institution type
             */
            type?: string | null;
        };
        /**
         * InstitutionRead
         * @description Representation returned by the API (output).
         */
        InstitutionRead: {
            /** Created At */
            created_at: string;
            /** Id */
            id: number;
            /** Latest Snapshot */
            latest_snapshot: string | null;
            /**
             * Name
             * @description Institution name
             */
            name: string;
            /**
             * Notes
             * @description Free-form notes
             */
            notes: string | null;
            /**
             * Snapshot Count
             * @description How much history this institution actually has. One situation is a state worth naming: nothing to compare against, and every quantity as old as that single day.
             * @default 0
             */
            snapshot_count: number;
            /**
             * Type
             * @description Institution type
             */
            type: string | null;
        };
        /**
         * InstrumentFamily
         * @description The same fund in its accumulating and distributing forms, together.
         */
        InstrumentFamily: {
            /** Key */
            key: string;
            /** Members */
            members: components["schemas"]["InstrumentMember"][];
        };
        /**
         * InstrumentMember
         * @description One instrument in the registry.
         *
         *     `base_ticker` is NOT a Yahoo symbol and `share_class_currency` is NOT the
         *     currency a holding trades in: the catalogue says EUNL and USD for iShares
         *     Core MSCI World, which Xetra trades in EUR. They are shown to help tell
         *     two similar rows apart, never to fill those fields.
         */
        InstrumentMember: {
            /** Base Ticker */
            base_ticker: string | null;
            /**
             * Distribution Policy
             * @description acc | dist
             */
            distribution_policy: string | null;
            /** Domicile */
            domicile: string | null;
            /** Hedged */
            hedged: boolean | null;
            /** Holdings Count */
            holdings_count: number | null;
            /** Isin */
            isin: string;
            /** Name */
            name: string;
            /** Replication */
            replication: string | null;
            /** Share Class Currency */
            share_class_currency: string | null;
            /** Size Meur */
            size_meur: number | null;
            /** Ter */
            ter: number | null;
        };
        /**
         * InstrumentSearch
         * @description `coverage` says how the match was made: 'all' means every word was
         *     found, 'partial' means the search had to loosen to find anything — a
         *     weaker claim about what was asked for, and the caller is expected to say
         *     so rather than present both the same way.
         */
        InstrumentSearch: {
            /**
             * Coverage
             * @default none
             */
            coverage: string;
            /** Families */
            families: components["schemas"]["InstrumentFamily"][];
            /** Fetched At */
            fetched_at: string | null;
            /** Retry After */
            retry_after: string | null;
            /**
             * Rows
             * @default 0
             */
            rows: number;
            /** Source */
            source: string | null;
            /**
             * State
             * @default ready
             * @enum {string}
             */
            state: "ready" | "downloading" | "failed" | "not_started";
        };
        /**
         * IsinSuggestion
         * @description A best-effort ISIN -> ticker suggestion from OpenFIGI.
         */
        IsinSuggestion: {
            /** Exchange */
            exchange: string | null;
            /** Name */
            name: string | null;
            /** Ticker */
            ticker: string | null;
            /** Type */
            type: string | null;
        };
        /**
         * LiabilityBalanceCreate
         * @description Payload to create a balance. liability_id comes from the URL.
         */
        LiabilityBalanceCreate: {
            /**
             * Balance
             * @description Outstanding principal at that date
             */
            balance: number;
            /**
             * Date
             * Format: date
             * @description Balance date (YYYY-MM-DD)
             */
            date: string;
            /**
             * Note
             * @description Free-form notes
             */
            note?: string | null;
        };
        /**
         * LiabilityBalanceRead
         * @description A stored balance as returned by the API.
         */
        LiabilityBalanceRead: {
            /**
             * Balance
             * @description Outstanding principal at that date
             */
            balance: number;
            /** Created At */
            created_at: string;
            /**
             * Date
             * Format: date
             * @description Balance date (YYYY-MM-DD)
             */
            date: string;
            /** Id */
            id: number;
            /** Liability Id */
            liability_id: number;
            /**
             * Note
             * @description Free-form notes
             */
            note: string | null;
        };
        /**
         * LiabilityCreate
         * @description Payload to create a liability.
         */
        LiabilityCreate: {
            /**
             * Currency
             * @description Currency, e.g. EUR
             */
            currency: string;
            /**
             * Interest Rate
             * @description Annual interest rate in % (e.g. 3.2)
             */
            interest_rate?: number | null;
            /**
             * Kind
             * @description Debt kind
             */
            kind?: string | null;
            /**
             * Name
             * @description Debt name (e.g. 'Home mortgage')
             */
            name: string;
            /**
             * Notes
             * @description Free-form notes
             */
            notes?: string | null;
            /**
             * Real Asset Id
             * @description Real asset this debt finances (mortgage -> house)
             */
            real_asset_id?: number | null;
        };
        /**
         * LiabilityRead
         * @description A stored liability. `latest_balance` = most recent outstanding balance.
         */
        LiabilityRead: {
            /** Created At */
            created_at: string;
            /**
             * Currency
             * @description Currency, e.g. EUR
             */
            currency: string;
            /** Id */
            id: number;
            /**
             * Interest Rate
             * @description Annual interest rate in % (e.g. 3.2)
             */
            interest_rate: number | null;
            /**
             * Kind
             * @description Debt kind
             */
            kind: string | null;
            /** Latest Balance */
            latest_balance: number | null;
            /**
             * Name
             * @description Debt name (e.g. 'Home mortgage')
             */
            name: string;
            /**
             * Notes
             * @description Free-form notes
             */
            notes: string | null;
            /**
             * Real Asset Id
             * @description Real asset this debt finances (mortgage -> house)
             */
            real_asset_id: number | null;
        };
        /**
         * MatrixCell
         * @description One asset class x region cell of the look-through, as a percent of the
         *     whole portfolio.
         */
        MatrixCell: {
            /** Asset Class */
            asset_class: string;
            /** Pct */
            pct: number;
            /** Region */
            region: string;
        };
        /**
         * NetWorthPoint
         * @description One point of the net-worth-over-time series (net = fin + real − debts).
         */
        NetWorthPoint: {
            /**
             * Base Currency
             * @description The currency this payload's computed amounts are in — the database's base, as the figures were converted. Figures a row states itself (an anchor, a transaction, a valuation) keep their own `currency`.
             */
            base_currency: string;
            /**
             * Date
             * Format: date
             */
            date: string;
            /** Financial */
            financial: number;
            /**
             * Fx As Of
             * @description The ECB day whose rates converted this point — the latest published on or before `date`. Null when nothing in the point needed converting.
             */
            fx_as_of: string | null;
            /** Liabilities */
            liabilities: number;
            /** Net Worth */
            net_worth: number;
            /** Real */
            real: number;
        };
        /**
         * OmittedPosition
         * @description Value a situation did not account for, with nothing on record saying
         *     where it went — a position it stopped naming, or units it stopped
         *     claiming.
         */
        OmittedPosition: {
            /** Asset Name */
            asset_name: string;
            /** Dropped On */
            dropped_on: string;
            /** Institution */
            institution: string | null;
            /** Institution Id */
            institution_id: number | null;
            /** Last Seen */
            last_seen: string;
            /** Last Value */
            last_value: number;
            /** Symbol */
            symbol: string | null;
            /**
             * Units Missing
             * @description Units the situation stopped claiming while still naming the row. Null when the whole position went unnamed, which is the difference between 'this is gone' and 'there is less of this than you had'.
             */
            units_missing: number | null;
        };
        /**
         * OverlapItem
         * @description A stock held inside 2+ funds: combined portfolio weight and the funds.
         */
        OverlapItem: {
            /** Funds */
            funds: string[];
            /** Name */
            name: string;
            /** Pct */
            pct: number;
        };
        /**
         * PlanTargetRead
         * @description A stored plan target as returned by the API.
         */
        PlanTargetRead: {
            /**
             * Asset Name
             * @description Name of the bought instrument (e.g. 'iShares World')
             */
            asset_name: string | null;
            /** Id */
            id: number;
            /**
             * Institution Id
             * @description Institution holding the bought investment
             */
            institution_id: number | null;
            /**
             * Isin
             * @description ISIN of the bought fund, for the look-through
             */
            isin: string | null;
            /** Position */
            position: number;
            /**
             * Symbol
             * @description Ticker of the bought instrument
             */
            symbol: string;
            /**
             * Weight
             * @description Share of the budget. Relative, not absolute: 1/1/1 and 40/30/30 both work.
             * @default 1
             */
            weight: number;
        };
        /**
         * PlanTargetWrite
         * @description One target of a plan a PERSON is writing. See `AccumulationPlanWrite`:
         *     `institution_id` is required here and required nowhere else.
         */
        PlanTargetWrite: {
            /**
             * Asset Name
             * @description Name of the bought instrument (e.g. 'iShares World')
             */
            asset_name?: string | null;
            /**
             * Institution Id
             * @description Where the bought position will be held. Required: a target that names no institution creates a position no situation can ever photograph and no close can settle.
             */
            institution_id: number;
            /**
             * Isin
             * @description ISIN of the bought fund, for the look-through
             */
            isin?: string | null;
            /**
             * Symbol
             * @description Ticker of the bought instrument
             */
            symbol: string;
            /**
             * Weight
             * @description Share of the budget. Relative, not absolute: 1/1/1 and 40/30/30 both work.
             * @default 1
             */
            weight?: number;
        };
        /**
         * Portfolio
         * @description The investment portfolio (latest snapshot of each institution).
         *     `priced` says whether any market prices are shown (freshly fetched or from
         *     the cache); `prices_as_of` is the OLDEST close date among the priced rows,
         *     so the user knows how stale the view can be. `total_realized` /
         *     `total_dividends` sum the gains locked in by sells and the dividends
         *     collected since each position's snapshot anchor.
         */
        Portfolio: {
            /**
             * Base Currency
             * @description The currency this payload's computed amounts are in — the database's base, as the figures were converted. Figures a row states itself (an anchor, a transaction, a valuation) keep their own `currency`.
             */
            base_currency: string;
            /**
             * Declared Instead
             * @description What those same situations declared that the app was not expecting. Three summary rows replaced by twenty-one positions is a portfolio described better, not their value lost, and naming only the first half cannot tell the reader which it is.
             */
            declared_instead: components["schemas"]["ArrivedPosition"][];
            /**
             * Fx As Of
             * @description ECB reference-rate date, present when any FX conversion was applied
             */
            fx_as_of: string | null;
            /** Priced */
            priced: boolean;
            /** Prices As Of */
            prices_as_of: string | null;
            /** Rows */
            rows: components["schemas"]["PortfolioRow"][];
            tax_estimate: components["schemas"]["TaxEstimate"];
            /**
             * Total Book
             * @description Sum of what the positions COST
             */
            total_book: number;
            /** Total Dividends */
            total_dividends: number;
            /**
             * Total Dividends Estimated
             * @description How much of `total_dividends` is still the market's gross figure (see PortfolioRow.dividends_estimated). The remainder is what the reader corrected by hand and is already net.
             */
            total_dividends_estimated: number;
            /**
             * Total Market
             * @description Sum of what they are WORTH: the market price where there is one, the last observed value where there is not. Null when nothing at all is priced. It is deliberately not the sum of the delta column: the rows the market could not price contribute their observation here, and no P/L.
             */
            total_market: number | null;
            /** Total Realized */
            total_realized: number;
            /**
             * Unconverted
             * @description Amounts that entered these totals without being converted, because no rate is known for the currency they are written in. The pair to `fx_as_of`: that says which rate was applied, this says what no rate could be applied to.
             */
            unconverted: components["schemas"]["UnconvertedAmount"][];
            /**
             * Unresolved Omissions
             * @description Positions a newer photograph stopped mentioning: their value left these totals without a line saying where it went.
             */
            unresolved_omissions: components["schemas"]["OmittedPosition"][];
        };
        /**
         * PortfolioComposition
         * @description The portfolio's REAL exposure: per-position resolution rows plus
         *     aggregated country/sector weights and cross-fund holding overlap.
         *     `coverage_pct` = share of the portfolio the look-through decomposed.
         */
        PortfolioComposition: {
            /**
             * Base Currency
             * @description The currency this payload's computed amounts are in — the database's base, as the figures were converted. Figures a row states itself (an anchor, a transaction, a valuation) keep their own `currency`.
             */
            base_currency: string;
            /**
             * Companies
             * @description Single-company exposure through the funds — the same data `overlap` is derived from, but complete instead of only the shared names.
             * @default []
             */
            companies: components["schemas"]["AllocationSlice"][];
            /** Countries */
            countries: components["schemas"]["AllocationSlice"][];
            /** Coverage Pct */
            coverage_pct: number;
            /**
             * Currencies
             * @description Currency the exposure really sits in, derived from the country weights (see app/geo.py for the stated limits — country of listing, no hedging).
             * @default []
             */
            currencies: components["schemas"]["AllocationSlice"][];
            /**
             * Matrix
             * @description Asset class x region
             * @default []
             */
            matrix: components["schemas"]["MatrixCell"][];
            /**
             * Notes
             * @description Why an axis is missing, when it is — so an empty chart never passes for 'you own nothing there'.
             * @default []
             */
            notes: string[];
            /** Overlap */
            overlap: components["schemas"]["OverlapItem"][];
            /** Rows */
            rows: components["schemas"]["CompositionRow"][];
            /** Sectors */
            sectors: components["schemas"]["AllocationSlice"][];
            /**
             * Total Value
             * @description What the looked-through portfolio is worth — the denominator the weights are shares of. Market where the market can price a position, its last observed value where it cannot.
             */
            total_value: number;
            /**
             * Undecomposed Pct
             * @description The share no source could decompose. Kept explicit so a chart can show it as its own slice instead of quietly normalising it away.
             * @default 0
             */
            undecomposed_pct: number;
        };
        /**
         * PortfolioRow
         * @description One investment position in the portfolio view, with its TWO readings
         *     kept apart: `book_value` is what the position cost, `observed_value` is
         *     what it is worth. They differ whenever a purchase price was recorded, and
         *     answering a question about worth with the cost is the defect this pair
         *     exists to end.
         *
         *     `market_value`/`delta` are filled only for quantity-based, symboled
         *     positions with a market price (live or cached); `as_of` is the close date
         *     that price refers to. An unpriced row still has an `observed_value` — the
         *     figure its last photograph recorded — and that is what it contributes to
         *     `total_market`.
         */
        PortfolioRow: {
            /**
             * As Of
             * @description Market close date the price refers to
             */
            as_of: string | null;
            /** Asset Class */
            asset_class: string | null;
            /** Asset Name */
            asset_name: string;
            /**
             * Avg Cost
             * @description book_value / quantity (average-cost accounting)
             */
            avg_cost: number | null;
            /**
             * Book Value
             * @description What this position COST, in the base currency: the recorded purchase price on a quantity-based holding where there is one, otherwise the value its photograph was taken at (and then cost_known is False, which is how a reader tells the two apart). A value-only lump keeps its photograph's figure here even when a cost was recorded against it — the projection has no units to merge a cost into, and the row says cost_known False rather than claim one. The base the P/L is measured against; never an answer to 'what is it worth'.
             */
            book_value: number;
            /**
             * Closed On
             * @description Set when a `close` disposed of this position: it is shown so the exit is visible, rather than the row simply ceasing to exist.
             */
            closed_on: string | null;
            /**
             * Cost Estimated
             * @description True when that recorded cost was DERIVED (e.g. from a broker's reported % return) rather than read off a contract note. A real number, but not a verified one, and the reader is entitled to know which.
             * @default false
             */
            cost_estimated: boolean;
            /**
             * Cost Known
             * @description False when the book comes from a snapshot with no recorded purchase: the 'average cost' is then a photograph's price, not money you paid, and 'P/L vs recorded' measures movement since you wrote it down.
             * @default false
             */
            cost_known: boolean;
            /**
             * Currency
             * @description Listing currency of the live price; null while it is not known, and then the row has no market value — a price in an unknown currency is not converted as if it were the base
             */
            currency: string | null;
            /**
             * Currency Note
             * @description Set when the hand-typed currency disagrees with the listing's own
             */
            currency_note: string | null;
            /**
             * Delta
             * @description market_value − book_value: what the market says today against what was paid. NULL when no quote priced the row — a photograph's own figure is not a price the market made, and putting the difference here would present a month-old statement as performance in the column that means 'a live market versus what you paid' on every other row. The movement is still visible: it is observed_value − book_value, from two named facts.
             */
            delta: number | null;
            /**
             * Delta Pct
             * @description delta / book_value — a return measured against cost
             */
            delta_pct: number | null;
            /** Distribution Policy */
            distribution_policy: string | null;
            /**
             * Dividends
             * @description Dividends collected since the snapshot anchor
             */
            dividends: number;
            /**
             * Dividends Estimated
             * @description The part of `dividends` still carrying the market's GROSS figure. An auto-recorded dividend is the declared amount per share, from which no withholding has been taken; correcting the row with the broker's real credit replaces it with the net figure and clears `estimated` in the same gesture. There is no gross/net column, so this is the only thing separating the rows a withholding estimate may be applied to from the rows where applying one would tax the same money twice.
             */
            dividends_estimated: number;
            /**
             * Institution
             * @description The institution holding this position, or null when it is held at none. Null is a real answer, not a missing name: a PAC target that names no institution creates positions like this, and they can never be photographed by a situation or reconciled against one. It used to arrive as the string '?', which a bank actually called that is indistinguishable from.
             */
            institution: string | null;
            /**
             * Institution Id
             * @description The id of the institution holding this position, for a caller that already has one and should not have to match on a name.
             */
            institution_id: number | null;
            /**
             * Last Dividend
             * @description The latest ex-date Yahoo lists for this ticker, from the dividend answers the catch-up keeps; null when it was never asked about or lists none. What the row says when no policy is stated and the ticker's own history decides its dividends.
             */
            last_dividend: string | null;
            /** Live Price */
            live_price: number | null;
            /**
             * Market Value
             * @description In the base currency (converted at the ECB reference rate)
             */
            market_value: number | null;
            /**
             * Observed On
             * @description The date this position was last CONFIRMED — the photo it sits in, or its most recent ledger entry. Two different things age: on a priced row the value is today's and only 'I hold N units' is this old; on an unpriced one, everything is. Callers must say which, not just 'stale'.
             */
            observed_on: string | null;
            /**
             * Observed Value
             * @description What this position was last OBSERVED to be worth: the figure its photograph recorded, carried forward through the ledger. Equal to book_value whenever the projection has only one figure to work from: no purchase price was recorded, or no value was (a quantity typed with no price is not an observation of zero), or the position was born in the ledger and no photograph ever saw it.
             */
            observed_value: number;
            /** Quantity */
            quantity: number | null;
            /** Quantity Age Days */
            quantity_age_days: number | null;
            /**
             * Realized Pl
             * @description Gains locked in by sells since the snapshot anchor
             */
            realized_pl: number;
            /** Symbol */
            symbol: string | null;
        };
        /**
         * PrefilledSnapshotRead
         * @description A snapshot started from the previous one, plus what the app did to it.
         *
         *     `needs_attention` is the point of the whole endpoint: it names the rows
         *     nothing could re-price, which are the only ones actually asking for the
         *     user. Everything else was carried over and valued at the new date.
         */
        PrefilledSnapshotRead: {
            /**
             * Base Currency
             * @description The currency this payload's computed amounts are in — the database's base, as the figures were converted. Figures a row states itself (an anchor, a transaction, a valuation) keep their own `currency`.
             */
            base_currency: string;
            /**
             * Copied From
             * @description Date of the situation it started from
             */
            copied_from: string;
            /** Created At */
            created_at: string;
            /**
             * Date
             * Format: date
             * @description Situation date (YYYY-MM-DD)
             */
            date: string;
            /** Id */
            id: number;
            /** Institution Id */
            institution_id: number;
            /**
             * Needs Attention
             * @description Rows carried over unchanged because nothing can price them
             */
            needs_attention: string[];
            /**
             * Note
             * @description Free-form notes
             */
            note: string | null;
            /**
             * Repriced
             * @description Tickers valued at the new date
             */
            repriced: string[];
            /**
             * Value Base
             * @description What this situation was worth, in `base_currency`: its holdings converted at the ECB rate, by the listing currency where the ticker has one. Computed by the router, never by the model.
             */
            value_base: number;
        };
        /**
         * PriceQuote
         * @description A market price for a symbol (the latest available close).
         *
         *     `name` is what the ticker actually resolved to. It is the check that
         *     catches a ticker pointing at the wrong fund — a plausible price never
         *     does, because the wrong fund has one too.
         */
        PriceQuote: {
            /**
             * As Of
             * Format: date
             */
            as_of: string;
            /** Currency */
            currency: string | null;
            /** Name */
            name: string | null;
            /** Price */
            price: number;
            /** Symbol */
            symbol: string;
        };
        /**
         * QuotableInstrument
         * @description A candidate from the live lookup — a share, ETF, coin or futures
         *     contract, i.e. everything the fund catalogue does not hold.
         *
         *     `price` NEVER travels without `exchange`, and for a measured reason: the
         *     lookup does not return a currency, so the same company on two exchanges
         *     comes back as two bare numbers in different money — one in dollars on NMS
         *     and one in euros on FRA, apart by the exchange rate and the same value. The
         *     currency arrives from a real quote once something is chosen.
         */
        QuotableInstrument: {
            /** Exchange */
            exchange: string | null;
            /** Name */
            name: string | null;
            /** Price */
            price: number | null;
            /**
             * Quote Type
             * @description equity | etf | cryptocurrency | future | index
             */
            quote_type: string | null;
            /** Symbol */
            symbol: string;
        };
        /**
         * RealAssetCreate
         * @description Payload to create a real asset.
         */
        RealAssetCreate: {
            /**
             * Acquisition Date
             * @description Acquisition date (YYYY-MM-DD)
             */
            acquisition_date?: string | null;
            /**
             * Acquisition Value
             * @description Value at acquisition time
             */
            acquisition_value?: number | null;
            /**
             * Category
             * @description Asset category
             */
            category?: string | null;
            /**
             * Currency
             * @description Currency, e.g. EUR
             */
            currency: string;
            /**
             * Name
             * @description Asset name (e.g. 'Milan flat', 'Tesla Model 3')
             */
            name: string;
            /**
             * Notes
             * @description Free-form notes
             */
            notes?: string | null;
        };
        /**
         * RealAssetRead
         * @description Representation of a real asset returned by the API.
         */
        RealAssetRead: {
            /**
             * Acquisition Date
             * @description Acquisition date (YYYY-MM-DD)
             */
            acquisition_date: string | null;
            /**
             * Acquisition Value
             * @description Value at acquisition time
             */
            acquisition_value: number | null;
            /**
             * Category
             * @description Asset category
             */
            category: string | null;
            /** Created At */
            created_at: string;
            /**
             * Currency
             * @description Currency, e.g. EUR
             */
            currency: string;
            /** Id */
            id: number;
            /**
             * Name
             * @description Asset name (e.g. 'Milan flat', 'Tesla Model 3')
             */
            name: string;
            /**
             * Notes
             * @description Free-form notes
             */
            notes: string | null;
        };
        /**
         * RealAssetValuationCreate
         * @description Payload to create a valuation. real_asset_id comes from the URL.
         */
        RealAssetValuationCreate: {
            /**
             * Date
             * Format: date
             * @description Valuation date (YYYY-MM-DD)
             */
            date: string;
            /**
             * Note
             * @description Free-form notes
             */
            note?: string | null;
            /**
             * Value
             * @description Asset value at that date
             */
            value: number;
        };
        /**
         * RealAssetValuationRead
         * @description Representation of a valuation returned by the API.
         */
        RealAssetValuationRead: {
            /** Created At */
            created_at: string;
            /**
             * Date
             * Format: date
             * @description Valuation date (YYYY-MM-DD)
             */
            date: string;
            /** Id */
            id: number;
            /**
             * Note
             * @description Free-form notes
             */
            note: string | null;
            /** Real Asset Id */
            real_asset_id: number;
            /**
             * Value
             * @description Asset value at that date
             */
            value: number;
        };
        /**
         * RealCategorySlice
         * @description One slice of the real allocation (by asset category).
         */
        RealCategorySlice: {
            /** Category */
            category: string;
            /** Value */
            value: number;
        };
        /**
         * RequiredReturnRequest
         * @description Inputs to compute the annual return needed to reach a target.
         */
        RequiredReturnRequest: {
            /**
             * Current Amount
             * @default 0
             */
            current_amount?: number;
            /**
             * Monthly Contribution
             * @default 0
             */
            monthly_contribution?: number;
            /** Target Amount */
            target_amount: number;
            /**
             * Target Date
             * Format: date
             */
            target_date: string;
        };
        /**
         * RequiredReturnResult
         * @description The computed required return (fraction; None if unreachable) + a note.
         */
        RequiredReturnResult: {
            /** Assessment */
            assessment: string;
            /** Required Annual Return */
            required_annual_return: number | null;
            /** Years */
            years: number;
        };
        /**
         * SnapshotCreate
         * @description Payload to create a snapshot. institution_id comes from the URL.
         *
         *     No currency: a situation has none of its own. Each holding states the
         *     currency it is in, and what the situation is worth is theirs converted.
         */
        SnapshotCreate: {
            /**
             * Date
             * Format: date
             * @description Situation date (YYYY-MM-DD)
             */
            date: string;
            /**
             * Note
             * @description Free-form notes
             */
            note?: string | null;
        };
        /**
         * SnapshotRead
         * @description Representation of a snapshot, and what it was worth.
         *
         *     The figure is named for its currency because it used to be named `value`
         *     and was a raw sum of whatever each holding happened to be denominated in.
         *     A name that says nothing about its unit is how a total in lira reached a
         *     screen with a euro sign on it, so the unit is declared beside it.
         */
        SnapshotRead: {
            /**
             * Base Currency
             * @description The currency this payload's computed amounts are in — the database's base, as the figures were converted. Figures a row states itself (an anchor, a transaction, a valuation) keep their own `currency`.
             */
            base_currency: string;
            /** Created At */
            created_at: string;
            /**
             * Date
             * Format: date
             * @description Situation date (YYYY-MM-DD)
             */
            date: string;
            /** Id */
            id: number;
            /** Institution Id */
            institution_id: number;
            /**
             * Note
             * @description Free-form notes
             */
            note: string | null;
            /**
             * Value Base
             * @description What this situation was worth, in `base_currency`: its holdings converted at the ECB rate, by the listing currency where the ticker has one. Computed by the router, never by the model.
             */
            value_base: number;
        };
        /**
         * SurveyAnswer
         * @description One questionnaire answer (financial-literacy intro or qualitative profile).
         */
        SurveyAnswer: {
            /** Answer */
            answer?: string | null;
            /** Question */
            question?: string | null;
            /** Question Key */
            question_key: string;
            /** Topic */
            topic?: string | null;
        };
        /**
         * SurveyAnswerRead
         * @description A stored survey answer as returned by the API.
         */
        SurveyAnswerRead: {
            /** Answer */
            answer: string | null;
            /** Created At */
            created_at: string;
            /** Id */
            id: number;
            /** Question */
            question: string | null;
            /** Question Key */
            question_key: string;
            /** Topic */
            topic: string | null;
        };
        /**
         * SymbolLookup
         * @description The live lane. Empty when nothing matched OR the source was unreachable —
         *     `reachable` tells the caller which, so an outage is never presented as
         *     'this instrument does not exist'.
         */
        SymbolLookup: {
            /**
             * Reachable
             * @default true
             */
            reachable: boolean;
            /** Results */
            results: components["schemas"]["QuotableInstrument"][];
        };
        /**
         * TaxCountryDefault
         * @description One row of the shipped default table, offered to the reader as a
         *     starting point and never applied behind their back.
         */
        TaxCountryDefault: {
            /** Capital Gains Rate */
            capital_gains_rate: number;
            /** Country */
            country: string;
            /** Dividend Withholding Rate */
            dividend_withholding_rate: number;
            /**
             * Omits
             * @description The carve-outs this flat rate knowingly flattens. Shipped WITH the number because it is what makes a three-country table honest rather than merely short.
             */
            omits: string;
            /**
             * Regime
             * @description The named regime the rate comes from
             */
            regime: string;
        };
        /**
         * TaxEstimate
         * @description A declared tax estimate, never a tax calculation — see app/tax.py for
         *     what is deliberately not being built here.
         *
         *     It rides on the portfolio payload because the two figures it is derived
         *     from are computed there, and a number that travels apart from its base
         *     drifts from it. It is in NO total on that payload: not the book value, not
         *     the market value, not the net worth. Beside them, labelled, carrying the
         *     rate it used — which is what separates an aid to deciding from something
         *     impersonating a return.
         *
         *     Every field may be null, and null means the reader has not said, which this
         *     app treats as a different claim from zero.
         */
        TaxEstimate: {
            /**
             * Capital Gains Rate
             * @description PERCENT, not a fraction. Null when the reader has not set it.
             */
            capital_gains_rate: number | null;
            /**
             * Capital Gains Tax
             * @description taxable_gain x the rate. Null when no rate is set.
             */
            capital_gains_tax: number | null;
            /**
             * Caveats
             * @description Why this figure is approximate, in words, generated beside the number. The page, the advisor and any outside assistant read the same list — a caveat kept only in the UI is one the chat would confidently omit.
             */
            caveats: string[];
            /**
             * Configured
             * @description Whether either rate is set at all. False is the state where the screen must say nobody has answered rather than show a zero — the bases below are still real and still worth reading.
             */
            configured: boolean;
            /**
             * Country
             * @description What the reader called their tax country. A LABEL on the estimate and the seed for the pre-filled rates — nothing downstream branches on it, so a country with no shipped default is not a lesser case.
             */
            country: string | null;
            /**
             * Dividend Withholding
             * @description dividends_gross_estimated x the rate. Null when no rate is set.
             */
            dividend_withholding: number | null;
            /**
             * Dividend Withholding Rate
             * @description PERCENT, not a fraction. Null when the reader has not set it.
             */
            dividend_withholding_rate: number | null;
            /**
             * Dividends Gross Estimated
             * @description The dividend base: ONLY the rows still marked estimated, which are the only ones still carrying a gross figure.
             */
            dividends_gross_estimated: number;
            /**
             * Dividends Recorded Net
             * @description The dividends the reader corrected by hand, which are already net of whatever their broker withheld. Named rather than omitted, because 'no rate was applied here' is a fact about the estimate.
             */
            dividends_recorded_net: number;
            /**
             * Missing Rates
             * @description Which rates a non-empty base is waiting on, so the screen can ask for exactly those.
             */
            missing_rates: string[];
            /**
             * Realized Gain
             * @description The ledger's realized result as-is, which may be NEGATIVE. Kept signed and separate from `taxable_gain` so a loss is visible as a loss instead of disappearing into a zero tax.
             */
            realized_gain: number;
            /**
             * Regime
             * @description The named regime behind a shipped default (e.g. 'Abgeltungsteuer 25% + 5.5% Solidaritätszuschlag'), so the reader can check the number against something. Null for a country this app ships no default for, including when the rates are set by hand.
             */
            regime: string | null;
            /**
             * Taxable Gain
             * @description max(realized_gain, 0) — the base the rate is applied to. A loss produces no negative tax here: it is not a refund, it is a carry-forward in most regimes, and this tracks neither.
             */
            taxable_gain: number;
            /**
             * Total
             * @description The two halves summed, and NULL whenever a base with something in it has no rate to apply. A total that quietly omitted half of itself would read as 'my tax' while being an understatement.
             */
            total: number | null;
        };
        /**
         * TaxSettings
         * @description The three settings the reader controls, as they are written and read.
         *
         *     Rates are PERCENT (26 means 26%), matching `Liability.interest_rate`, the
         *     one rate this app already stored. Null clears the key.
         */
        TaxSettings: {
            /** Capital Gains Rate */
            capital_gains_rate?: number | null;
            /**
             * Country
             * @description Free text: any country, listed or not
             */
            country?: string | null;
            /** Dividend Withholding Rate */
            dividend_withholding_rate?: number | null;
        };
        /**
         * TaxSettingsRead
         * @description What the reader set, plus the defaults they could choose from.
         *
         *     The known list travels with the current values so the screen has one round
         *     trip and one source of truth for the rates — a table duplicated into the
         *     frontend is a table that goes stale on one side.
         */
        TaxSettingsRead: {
            /** Capital Gains Rate */
            capital_gains_rate: number | null;
            /**
             * Country
             * @description Free text: any country, listed or not
             */
            country: string | null;
            /** Dividend Withholding Rate */
            dividend_withholding_rate: number | null;
            /** Known Countries */
            known_countries: components["schemas"]["TaxCountryDefault"][];
        };
        /**
         * TransactionRead
         * @description A stored transaction as returned by the API.
         */
        TransactionRead: {
            /** Amount */
            amount: number;
            /**
             * Asset Class
             * @description equity | bond | fund_etf | crypto | ...
             */
            asset_class: string | null;
            /**
             * Asset Name
             * @description Instrument name
             */
            asset_name: string;
            /**
             * Cash Institution Id
             * @description Institution whose cash paid (defaults to institution_id)
             */
            cash_institution_id: number | null;
            /** Created At */
            created_at: string;
            /**
             * Currency
             * @description Currency of `amount` and `fees`: the cash that left or reached the account, e.g. EUR
             */
            currency: string;
            /**
             * Currency Note
             * @description Set when `price_currency` disagrees with the currency the listing actually trades in, so the entry is worth opening and correcting.
             */
            currency_note: string | null;
            /**
             * Date
             * Format: date
             * @description Actual execution date
             */
            date: string;
            /**
             * Estimated
             * @description Priced at the market close, not a real broker fill
             */
            estimated: boolean;
            /**
             * Fees
             * @description Broker fees/commissions, in `currency`
             * @default 0
             */
            fees: number;
            /**
             * Fx As Of
             * @description The ECB day whose rate turned quantity x unit_price into `amount`, when the app derived it across two currencies. Null when there was nothing to convert, or when the amount is the reader's own figure.
             */
            fx_as_of: string | null;
            /** Id */
            id: number;
            /**
             * Institution Id
             * @description Institution holding the position this entry moves
             */
            institution_id: number | null;
            /**
             * Isin
             * @description Fund ISIN, when known
             */
            isin: string | null;
            /**
             * Kind
             * @description buy | sell | dividend | close
             * @default buy
             */
            kind: string;
            /**
             * Note
             * @description Free-form notes
             */
            note: string | null;
            /** Plan Id */
            plan_id: number | null;
            /** Plan Occurrence */
            plan_occurrence: string | null;
            /**
             * Price Currency
             * @description Currency of `unit_price` — the listing's, e.g. USD. Required for a buy, a sell and a dividend; a close has no price and leaves it empty.
             */
            price_currency: string | null;
            /**
             * Quantity
             * @description Units moved; for a dividend, the units held at the ex-date
             * @default 0
             */
            quantity: number;
            /**
             * Symbol
             * @description Yahoo ticker (e.g. VWCE.MI)
             */
            symbol: string | null;
            /**
             * Unit Price
             * @description Price per unit; for a dividend, the dividend per share
             * @default 0
             */
            unit_price: number;
        };
        /**
         * TransactionWrite
         * @description What a PERSON may post to `/api/transactions` — which is not the same
         *     thing as what the ledger is able to store.
         *
         *     `institution_id` is required here and required nowhere else. A row with
         *     NEITHER institution column set is skipped by the cash register, which keeps
         *     only the entries belonging to the institution it is computing and finds
         *     that `None` equals no id there is; the position the same row creates is
         *     bucketed under `None` and counted in full. One half of the transaction is
         *     addressed to an institution and the other half to nobody, so the money
         *     spent never leaves an account and the purchase adds its own cost to the net
         *     worth. Measured: one institution holding 1000, a buy of 10 units at 10.00
         *     with no institution named, and the net worth went from 1000.00 to 1100.00.
         *
         *     It is the CASH side that makes this required rather than any preference of
         *     the schema's — the money came from somewhere, and with no institution named
         *     the app has nowhere to take it from.
         *
         *     The column stays nullable and `TransactionCreate` stays loose on purpose:
         *     the PAC writes rows with no HOLDING institution (a plan target that names
         *     none) while always naming the PAYING one, and those rows are unreachable
         *     but arithmetically right. Requiring the field of them is a separate
         *     decision. This subclass narrows the one door a reader posts through, and
         *     leaves the internal one alone.
         */
        TransactionWrite: {
            /**
             * Amount
             * @description Actual cash moved, never negative, in `currency`. Defaults to quantity*unit_price + fees for a buy, and quantity*unit_price - fees (net proceeds) for a sell or dividend — with quantity*unit_price converted from `price_currency` at the rates of `date` when the two currencies differ. A close has no units to derive it from, so it must state it — 0 is allowed, silence is not.
             */
            amount?: number | null;
            /**
             * Asset Class
             * @description equity | bond | fund_etf | crypto | ...
             */
            asset_class?: string | null;
            /**
             * Asset Name
             * @description Instrument name
             */
            asset_name: string;
            /**
             * Cash Institution Id
             * @description Institution whose cash paid (defaults to institution_id)
             */
            cash_institution_id?: number | null;
            /**
             * Currency
             * @description Currency of `amount` and `fees`: the cash that left or reached the account, e.g. EUR
             */
            currency: string;
            /**
             * Date
             * Format: date
             * @description Actual execution date
             */
            date: string;
            /**
             * Fees
             * @description Broker fees/commissions, in `currency`
             * @default 0
             */
            fees?: number;
            /**
             * Institution Id
             * @description Where the position is held — and, unless cash_institution_id says otherwise, whose cash moves. Required: an entry naming no institution spends money no account ever loses.
             */
            institution_id: number;
            /**
             * Isin
             * @description Fund ISIN, when known
             */
            isin?: string | null;
            /**
             * Kind
             * @description buy | sell | dividend | close
             * @default buy
             */
            kind?: string;
            /**
             * Note
             * @description Free-form notes
             */
            note?: string | null;
            /**
             * Price Currency
             * @description Currency of `unit_price` — the listing's, e.g. USD. Required for a buy, a sell and a dividend; a close has no price and leaves it empty.
             */
            price_currency?: string | null;
            /**
             * Quantity
             * @description Units moved; for a dividend, the units held at the ex-date
             * @default 0
             */
            quantity?: number;
            /**
             * Symbol
             * @description Yahoo ticker (e.g. VWCE.MI)
             */
            symbol?: string | null;
            /**
             * Unit Price
             * @description Price per unit; for a dividend, the dividend per share
             * @default 0
             */
            unit_price?: number;
        };
        /**
         * TransferCreate
         * @description Payload to create a transfer.
         */
        TransferCreate: {
            /**
             * Amount
             * @description Amount that left the source, in `currency`
             */
            amount: number;
            /**
             * Currency
             * @description Currency of the source side, e.g. EUR
             */
            currency: string;
            /**
             * Date
             * Format: date
             * @description Transfer date (YYYY-MM-DD)
             */
            date: string;
            /**
             * From Institution Id
             * @description Source institution id
             */
            from_institution_id?: number | null;
            /**
             * Note
             * @description Free-form notes
             */
            note?: string | null;
            /**
             * To Amount
             * @description Amount that reached the destination, in `to_currency`, from its statement. Left out, it is `amount` when the two currencies are the same, and otherwise worked out at the ECB rate final for `date`.
             */
            to_amount?: number | null;
            /**
             * To Currency
             * @description Currency of the destination side, e.g. EUR
             */
            to_currency: string;
            /**
             * To Institution Id
             * @description Target institution id
             */
            to_institution_id?: number | null;
        };
        /**
         * TransferRead
         * @description A stored transfer as returned by the API.
         */
        TransferRead: {
            /**
             * Amount
             * @description Amount that left the source, in `currency`
             */
            amount: number;
            /** Created At */
            created_at: string;
            /**
             * Currency
             * @description Currency of the source side, e.g. EUR
             */
            currency: string;
            /**
             * Date
             * Format: date
             * @description Transfer date (YYYY-MM-DD)
             */
            date: string;
            /**
             * From Institution Id
             * @description Source institution id
             */
            from_institution_id: number | null;
            /**
             * Fx As Of
             * @description The ECB day whose rate `to_amount` was worked out at; null when it was stated, or when both sides share a currency
             */
            fx_as_of: string | null;
            /** Id */
            id: number;
            /**
             * Note
             * @description Free-form notes
             */
            note: string | null;
            /** To Amount */
            to_amount: number;
            /**
             * To Currency
             * @description Currency of the destination side, e.g. EUR
             */
            to_currency: string;
            /**
             * To Institution Id
             * @description Target institution id
             */
            to_institution_id: number | null;
        };
        /**
         * UnconvertedAmount
         * @description Value that reached a total in the currency it was written in, because the
         *     app has no rate to convert it with.
         *
         *     The fallback itself is deliberate: an amount the feed has never priced is
         *     kept rather than dropped, since a total quietly short by a whole account is
         *     as wrong as one quietly inflated (`fx.Converter.to_base_or_as_stored`). What
         *     was missing is this — the saying so. Two cases reach it and the reader tells
         *     them apart at a glance, which is why the code is printed as typed: a code
         *     that is a typo (`Doll`) is corrected on the row, and a real currency the ECB
         *     does not quote (`TWD`) cannot be converted by anybody and the figure simply
         *     is in another unit.
         */
        UnconvertedAmount: {
            /**
             * Amount
             * @description What those amounts come to in THEIR OWN unit, as they were written. A sum over rows, and not the amount any figure above is wrong by — nor a bound on it, in either direction. One converter serves several totals, so the same currency can arrive as a value and again as its cost, and a debt's balance adds here while it subtracts there; and a recurring flow is converted ONCE and multiplied afterwards. Measured: a holding worth 1,000 TWD that cost 900 reports 1,900.00 against an investments total of 1,000.00; an asset and a debt of 1,000 TWD each add 2,000.00 here while the net worth does not move; and 100 TWD a month against a year-old anchor puts 1,200.00 into the net worth and reports 100.00.
             */
            amount: number;
            /**
             * Count
             * @description How many amounts were passed through
             */
            count: number;
            /**
             * Currency
             * @description The code as the row states it, or null for a row with none
             */
            currency: string | null;
        };
        /** ValidationError */
        ValidationError: {
            /** Context */
            ctx?: Record<string, never>;
            /** Input */
            input?: unknown;
            /** Location */
            loc: (string | number)[];
            /** Message */
            msg: string;
            /** Error Type */
            type: string;
        };
        /**
         * WatchlistItemRead
         * @description A stored watchlist line as the API returns it.
         */
        WatchlistItemRead: {
            /** Added At */
            added_at: string;
            /**
             * Based On
             * @description What the reader declared that this rests on
             */
            based_on: string;
            /** Id */
            id: number;
            /**
             * Isin
             * @description A fund's ISIN, from the catalogue: its identity. Null on a share's line, which the symbol identifies
             */
            isin: string | null;
            /**
             * Name
             * @description The instrument's name, as the catalogue or Yahoo writes it
             */
            name: string;
            /**
             * Reason
             * @description Why this was suggested
             */
            reason: string;
            /**
             * Symbol
             * @description On a fund's line, a quotable symbol from the live lookup if one was found, never the catalogue's `base_ticker`, which is not a Yahoo symbol. On a share's line, the identity: the symbol Yahoo lists it under.
             */
            symbol: string | null;
            /**
             * Unknowns
             * @description What the suggestion does NOT know about them
             */
            unknowns: string;
        };
    };
    responses: never;
    parameters: never;
    requestBodies: never;
    headers: never;
    pathItems: never;
}
export type $defs = Record<string, never>;
export interface operations {
    list_accumulation_plans_api_accumulation_plans_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AccumulationPlanRead"][];
                };
            };
        };
    };
    create_accumulation_plan_api_accumulation_plans_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["AccumulationPlanWrite"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AccumulationPlanRead"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_accumulation_plan_api_accumulation_plans__plan_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                plan_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AccumulationPlanRead"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    update_accumulation_plan_api_accumulation_plans__plan_id__put: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                plan_id: number;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["AccumulationPlanWrite"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AccumulationPlanRead"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    delete_accumulation_plan_api_accumulation_plans__plan_id__delete: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                plan_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_chain_runs_api_advisor_chain_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ChainRunSummary"][];
                };
            };
        };
    };
    get_chain_run_api_advisor_chain__run_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                run_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ChainRunRead"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_all_cash_anchors_api_cash_anchors_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CashAnchorRead"][];
                };
            };
        };
    };
    get_cash_anchor_api_cash_anchors__anchor_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                anchor_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CashAnchorRead"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    update_cash_anchor_api_cash_anchors__anchor_id__put: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                anchor_id: number;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["CashAnchorCreate"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CashAnchorRead"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    delete_cash_anchor_api_cash_anchors__anchor_id__delete: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                anchor_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_cash_positions_api_cash_positions_get: {
        parameters: {
            query?: {
                as_of?: string | null;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CashPosition"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    send_api_chat_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ChatRequest"];
            };
        };
        responses: {
            /** @description Server-sent events: `start`, then `decided`/`thought`/`delta`/`tool`/`source`/`step`/`card` as they happen, then exactly one `done` or one `error`. */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ChatStart"] | components["schemas"]["ChatThought"] | components["schemas"]["ChatDelta"] | components["schemas"]["ChatTool"] | components["schemas"]["ChatSource"] | components["schemas"]["ChatStep"] | components["schemas"]["ChatCard"] | components["schemas"]["ChatDecided"] | components["schemas"]["ChatDone"] | components["schemas"]["ChatError"];
                    "text/event-stream": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    decide_api_chat_cards__card_id__post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                card_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ChatCardDecision"];
            };
        };
        responses: {
            /** @description Server-sent events: `start`, then `decided`/`thought`/`delta`/`tool`/`source`/`step`/`card` as they happen, then exactly one `done` or one `error`. */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ChatStart"] | components["schemas"]["ChatThought"] | components["schemas"]["ChatDelta"] | components["schemas"]["ChatTool"] | components["schemas"]["ChatSource"] | components["schemas"]["ChatStep"] | components["schemas"]["ChatCard"] | components["schemas"]["ChatDecided"] | components["schemas"]["ChatDone"] | components["schemas"]["ChatError"];
                    "text/event-stream": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_conversations_api_chat_conversations_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ChatConversationRead"][];
                };
            };
        };
    };
    get_conversation_api_chat_conversations__conversation_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                conversation_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ChatConversationDetail"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    delete_conversation_api_chat_conversations__conversation_id__delete: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                conversation_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_models_api_chat_models_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ChatModelsRead"];
                };
            };
        };
    };
    get_allocation_api_dashboard_allocation_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["DashboardAllocation"];
                };
            };
        };
    };
    get_cashflow_api_dashboard_cashflow_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CashFlowSummary"];
                };
            };
        };
    };
    get_net_worth_series_api_dashboard_net_worth_series_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["NetWorthPoint"][];
                };
            };
        };
    };
    get_portfolio_api_dashboard_portfolio_get: {
        parameters: {
            query?: {
                live?: boolean;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Portfolio"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_portfolio_composition_api_dashboard_portfolio_composition_get: {
        parameters: {
            query?: {
                refresh?: boolean;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PortfolioComposition"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_summary_api_dashboard_summary_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["DashboardSummary"];
                };
            };
        };
    };
    list_items_api_expenses_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ExpenseRead"][];
                };
            };
        };
    };
    create_item_api_expenses_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ExpenseCreate"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ExpenseRead"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_item_api_expenses__item_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                item_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ExpenseRead"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    update_item_api_expenses__item_id__put: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                item_id: number;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ExpenseCreate"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ExpenseRead"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    delete_item_api_expenses__item_id__delete: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                item_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_fx_rates_api_fx_rates_get: {
        parameters: {
            query?: {
                refresh?: boolean;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FxRateRead"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_goals_api_goals_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["GoalRead"][];
                };
            };
        };
    };
    create_goal_api_goals_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["GoalCreate"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["GoalRead"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_goal_api_goals__goal_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                goal_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["GoalRead"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    update_goal_api_goals__goal_id__put: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                goal_id: number;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["GoalCreate"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["GoalRead"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    delete_goal_api_goals__goal_id__delete: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                goal_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    health_api_health_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
        };
    };
    get_holding_api_holdings__holding_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                holding_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HoldingRead"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    update_holding_api_holdings__holding_id__put: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                holding_id: number;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["HoldingCreate"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HoldingRead"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    delete_holding_api_holdings__holding_id__delete: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                holding_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    refresh_holding_price_api_holdings__holding_id__refresh_price_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                holding_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HoldingRead"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_items_api_income_sources_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["IncomeSourceRead"][];
                };
            };
        };
    };
    create_item_api_income_sources_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["IncomeSourceCreate"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["IncomeSourceRead"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_item_api_income_sources__item_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                item_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["IncomeSourceRead"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    update_item_api_income_sources__item_id__put: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                item_id: number;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["IncomeSourceCreate"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["IncomeSourceRead"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    delete_item_api_income_sources__item_id__delete: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                item_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_institutions_api_institutions_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["InstitutionRead"][];
                };
            };
        };
    };
    create_institution_api_institutions_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["InstitutionCreate"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["InstitutionRead"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_institution_api_institutions__institution_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                institution_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["InstitutionRead"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    update_institution_api_institutions__institution_id__put: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                institution_id: number;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["InstitutionCreate"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["InstitutionRead"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    delete_institution_api_institutions__institution_id__delete: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                institution_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_cash_position_api_institutions__institution_id__cash_get: {
        parameters: {
            query?: {
                as_of?: string | null;
            };
            header?: never;
            path: {
                institution_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CashPosition"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_cash_anchors_api_institutions__institution_id__cash_anchors_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                institution_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CashAnchorRead"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    create_cash_anchor_api_institutions__institution_id__cash_anchors_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                institution_id: number;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["CashAnchorCreate"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CashAnchorRead"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_snapshots_api_institutions__institution_id__snapshots_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                institution_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SnapshotRead"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    create_snapshot_api_institutions__institution_id__snapshots_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                institution_id: number;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["SnapshotCreate"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SnapshotRead"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    create_prefilled_snapshot_api_institutions__institution_id__snapshots_prefilled_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                institution_id: number;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["SnapshotCreate"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PrefilledSnapshotRead"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    catalogue_status_api_instruments_catalogue_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CatalogueStatus"];
                };
            };
        };
    };
    ensure_catalogue_api_instruments_catalogue_ensure_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CatalogueStatus"];
                };
            };
        };
    };
    refresh_catalogue_api_instruments_catalogue_refresh_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CatalogueStatus"];
                };
            };
        };
    };
    lookup_symbols_api_instruments_lookup_get: {
        parameters: {
            query?: {
                limit?: number;
                /** @description Free text: company, coin, ticker */
                q?: string;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SymbolLookup"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    search_instruments_api_instruments_search_get: {
        parameters: {
            query?: {
                limit?: number;
                /** @description Free text: name, issuer, ticker */
                q?: string;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["InstrumentSearch"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_liabilities_api_liabilities_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["LiabilityRead"][];
                };
            };
        };
    };
    create_liability_api_liabilities_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["LiabilityCreate"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["LiabilityRead"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_liability_api_liabilities__liability_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                liability_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["LiabilityRead"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    update_liability_api_liabilities__liability_id__put: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                liability_id: number;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["LiabilityCreate"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["LiabilityRead"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    delete_liability_api_liabilities__liability_id__delete: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                liability_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_balances_api_liabilities__liability_id__balances_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                liability_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["LiabilityBalanceRead"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    create_balance_api_liabilities__liability_id__balances_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                liability_id: number;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["LiabilityBalanceCreate"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["LiabilityBalanceRead"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    update_balance_api_liability_balances__balance_id__put: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                balance_id: number;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["LiabilityBalanceCreate"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["LiabilityBalanceRead"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    delete_balance_api_liability_balances__balance_id__delete: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                balance_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    required_return_api_planning_required_return_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["RequiredReturnRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RequiredReturnResult"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_listing_currencies_api_prices_listing_currencies_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: string;
                    };
                };
            };
        };
    };
    get_quote_api_prices_quote_get: {
        parameters: {
            query: {
                /** @description Close on/just before this date, for recording a past purchase */
                on?: string | null;
                symbol: string;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PriceQuote"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    resolve_isin_api_prices_resolve_get: {
        parameters: {
            query: {
                isin: string;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["IsinSuggestion"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_valuation_api_real_asset_valuations__valuation_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                valuation_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RealAssetValuationRead"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    update_valuation_api_real_asset_valuations__valuation_id__put: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                valuation_id: number;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["RealAssetValuationCreate"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RealAssetValuationRead"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    delete_valuation_api_real_asset_valuations__valuation_id__delete: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                valuation_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_real_assets_api_real_assets_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RealAssetRead"][];
                };
            };
        };
    };
    create_real_asset_api_real_assets_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["RealAssetCreate"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RealAssetRead"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_real_asset_api_real_assets__real_asset_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                real_asset_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RealAssetRead"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    update_real_asset_api_real_assets__real_asset_id__put: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                real_asset_id: number;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["RealAssetCreate"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RealAssetRead"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    delete_real_asset_api_real_assets__real_asset_id__delete: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                real_asset_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_valuations_api_real_assets__real_asset_id__valuations_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                real_asset_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RealAssetValuationRead"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    create_valuation_api_real_assets__real_asset_id__valuations_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                real_asset_id: number;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["RealAssetValuationCreate"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RealAssetValuationRead"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_base_currency_api_settings_base_currency_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["BaseCurrencySettingRead"];
                };
            };
        };
    };
    put_base_currency_api_settings_base_currency_put: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["BaseCurrencySetting"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["BaseCurrencySettingRead"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_tax_settings_api_settings_tax_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["TaxSettingsRead"];
                };
            };
        };
    };
    put_tax_settings_api_settings_tax_put: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["TaxSettings"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["TaxSettingsRead"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_snapshot_api_snapshots__snapshot_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                snapshot_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SnapshotRead"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    update_snapshot_api_snapshots__snapshot_id__put: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                snapshot_id: number;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["SnapshotCreate"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SnapshotRead"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    delete_snapshot_api_snapshots__snapshot_id__delete: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                snapshot_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_holdings_api_snapshots__snapshot_id__holdings_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                snapshot_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HoldingRead"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    create_holding_api_snapshots__snapshot_id__holdings_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                snapshot_id: number;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["HoldingCreate"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HoldingRead"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_survey_api_survey_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SurveyAnswerRead"][];
                };
            };
        };
    };
    put_survey_api_survey_put: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["SurveyAnswer"][];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SurveyAnswerRead"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_transactions_api_transactions_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["TransactionRead"][];
                };
            };
        };
    };
    create_transaction_api_transactions_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["TransactionWrite"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["TransactionRead"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_transaction_api_transactions__tx_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                tx_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["TransactionRead"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    update_transaction_api_transactions__tx_id__put: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                tx_id: number;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["TransactionWrite"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["TransactionRead"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    delete_transaction_api_transactions__tx_id__delete: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                tx_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    catch_up_api_transactions_catch_up_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CatchUpResult"];
                };
            };
        };
    };
    list_transfers_api_transfers_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["TransferRead"][];
                };
            };
        };
    };
    create_transfer_api_transfers_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["TransferCreate"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["TransferRead"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_transfer_api_transfers__transfer_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                transfer_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["TransferRead"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    update_transfer_api_transfers__transfer_id__put: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                transfer_id: number;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["TransferCreate"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["TransferRead"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    delete_transfer_api_transfers__transfer_id__delete: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                transfer_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_watchlist_api_watchlist_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["WatchlistItemRead"][];
                };
            };
        };
    };
    delete_watchlist_item_api_watchlist__item_id__delete: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                item_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
}
