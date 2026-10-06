/* Archivo's advance widths at weight 400, in font units (1000 to the em), for
   printable ASCII: the characters the forms' questions are written in.

   Taken once from public/fonts/archivo-latin.woff2 with fontTools, the
   variable font instanced at wght 400 first. Its default instance is 600,
   and reading that would overstate every question by 2 to 6px at 14px:
   "How many?" is 76.0 there and 74.0 here, as the inputs render it.

     from fontTools.ttLib import TTFont
     from fontTools.varLib import instancer
     f = instancer.instantiateVariableFont(
         TTFont("public/fonts/archivo-latin.woff2"), {"wght": 400})
     cmap, hmtx = f.getBestCmap(), f["hmtx"].metrics
     {chr(c): hmtx[cmap[c]][0] for c in range(32, 127)}

   Kerning is left out. The fit test's slack is what absorbs it. */

export const UNITS_PER_EM = 1000;

export const ARCHIVO_400: Record<string, number> = {
  " ": 209, "!": 273, "\"": 374, "#": 582, "$": 510, "%": 950, "&": 692, "'": 209,
  "(": 355, ")": 355, "*": 407, "+": 625, ",": 277, "-": 333, ".": 277, "/": 294,
  "0": 573, "1": 521, "2": 567, "3": 573, "4": 555, "5": 571, "6": 573, "7": 553,
  "8": 574, "9": 573, ":": 296, ";": 296, "<": 625, "=": 625, ">": 625, "?": 578,
  "@": 1005, "A": 682, "B": 698, "C": 728, "D": 734, "E": 677, "F": 612, "G": 796,
  "H": 736, "I": 267, "J": 559, "K": 662, "L": 536, "M": 847, "N": 736, "O": 788,
  "P": 665, "Q": 788, "R": 727, "S": 673, "T": 606, "U": 731, "V": 648, "W": 924,
  "X": 680, "Y": 655, "Z": 635, "[": 296, "\\": 294, "]": 296, "^": 625, "_": 485,
  "`": 187, "a": 545, "b": 567, "c": 519, "d": 567, "e": 548, "f": 280, "g": 556,
  "h": 563, "i": 225, "j": 223, "k": 514, "l": 225, "m": 860, "n": 563, "o": 570,
  "p": 567, "q": 567, "r": 332, "s": 510, "t": 297, "u": 562, "v": 504, "w": 723,
  "x": 513, "y": 504, "z": 498, "{": 353, "|": 245, "}": 353, "~": 625,
};
