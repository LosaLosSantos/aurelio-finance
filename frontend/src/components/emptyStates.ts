/* What every empty section says (brief BC): what the section is for and the
   first step, in the reader's words, and where that step is taken.

   Most of them used to be one bare line ("No income yet.", "No anchors
   yet."): true, and no help to someone opening the app for the first time.
   The words live here, one per section, so a test reads them all. A section
   that shares its page with others keeps a line (Cash flow has four: four
   emblems on one page would be too many); the two pages that are empty as a
   whole keep their emblem panel, and theirs carries a button to where the
   first step is taken.

   The reader's words: a bank or broker, not an institution; a cash balance,
   not an anchor; what an account held on a day, said once beside the word
   "situation" the page uses.

   No runtime imports, so `npm test` reaches it. */

/** An empty page's panel: its title, its sentence and its button. */
export interface EmptyPanel {
  title: string;
  text: string;
  action: string;
}

export const EMPTY_PANELS = {
  dashboard: {
    title: "Nothing to show yet",
    text: "Your net worth and its history are drawn from what you record. Start with the bank or broker that holds your money: add it in Records, with the cash it holds.",
    action: "Add a bank or broker",
  },
  portfolio: {
    title: "Nothing invested yet",
    text: "Your investments appear here, priced at the market. Record them in Records: a bank or broker, then a situation (what it held on a day) with each holding in it; a holding with a ticker is priced on its own.",
    action: "Add a bank or broker",
  },
} satisfies Record<string, EmptyPanel>;

/** An empty section's line. */
export const EMPTY_LINES = {
  savingsRate: "Shown once an income is recorded in Records → Cash flow: the share of it left after your expenses.",
  lookThrough:
    "Nothing to look inside yet. Once a situation in Records holds a fund, this shows its countries, sectors and the companies you own through more than one.",
  watchlist:
    "Nothing on the watchlist yet. Ask the chat what you might look at: an idea you add from its card lands here, with its reasoning.",
  ledger:
    "No entries yet. Record a buy, a sale or a dividend with the form above, as your statement shows it; a PAC's buys and dividends are added here by themselves when the app starts.",
  institutions:
    "No bank or broker yet. Add the first one above: its name is enough. Each keeps its own cash and what you held there on each day.",
  cash: "No cash balance yet. Type what this account held on a day above (today's is fine): the income, expenses and transfers you link to it are added from that day.",
  situations:
    "No situation yet. A situation is what this account held on a day: pick the day above and press Declare the first situation, then add each holding.",
  situation: "Nothing recorded on this day yet. Add each holding the account held, starting with its group above.",
  realAssets:
    "No real assets yet. A home, land or anything of value you own outside an account: name it above, then open it to say what it is worth.",
  valuations: "No value yet. Type what it was worth on a day above: your net worth counts the latest.",
  debts:
    "No debts recorded. A mortgage or a loan goes here: name it above, then open it to say what is left to repay; your net worth subtracts it.",
  balances:
    "No balance yet. Type what was left to repay on a day above, as your statement shows it: your net worth subtracts the latest.",
  income:
    "No income yet. Add what comes in above, a salary or a rent you receive: it is credited to the account you pick, from its first payment.",
  expenses:
    "No expenses yet. Add what goes out above, rent or groceries: it is paid from the account you pick, from its first payment.",
  pac: "No PAC yet. A plan that buys the same funds on a schedule goes above: how much, into what, how often; each buy is then recorded on its day.",
  transfers: "No transfers yet. Cash moved between two of your accounts goes above, on the day it moved.",
  goals: "No goals yet. Choose above what one is for and add it: it is saved with the rest of your profile.",
} satisfies Record<string, string>;
