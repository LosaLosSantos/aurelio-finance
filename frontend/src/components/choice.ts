/* One of a few answers to press, as classes (brief AY): the Profile's yes/no
   questions and the Theme card.

   The chosen one is filled with the olive tint, framed in the olive and
   underscored, so it is told from the others by more than its colour (WCAG
   1.4.1), as the nav underscores the page it is on. The underscore takes no
   room: the chosen button and the others keep the same box, so pressing an
   answer moves nothing (a bolder word would widen it). Its button says
   `aria-pressed`.

   No runtime imports, so `npm test` reaches it. */

export function choiceClass(chosen: boolean): string {
  return (
    "rounded-sm border px-3 py-1.5 text-sm transition " +
    (chosen
      ? "border-olive bg-olive-tint text-olive-deep underline decoration-2 underline-offset-4"
      : "border-rule text-ink-soft hover:bg-ground")
  );
}
