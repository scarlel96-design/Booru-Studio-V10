# Booru Studio Design System — Direction Lock

Booru Studio does **not** imitate four operating systems by mixing visual ornaments. It extracts the
reasoning behind their strongest conventions and expresses one coherent desktop product language.

## Four-source synthesis

- **Apple / iOS / macOS:** purpose, hierarchy, restraint, craft, precise typography, calm depth and
  materials only where they clarify functional layers. Simplicity means focus, not empty minimalism.
- **Samsung One UI:** separate glanceable/viewing information from the interaction zone, use generous
  breathing room, strong visual anchors and controls that remain easy to reach and identify.
- **Windows 11:** effortless/calm/familiar/coherent desktop behavior, standard placement, predictable
  navigation and settings concepts.
- **Windows 10 familiarity:** retain the settings mental model users already understand: top-level
  categories, left navigation, searchable settings, clear descriptions, toggles/choices on the right,
  Advanced content progressively disclosed rather than scattered across custom dialogs.

## Booru Studio rules

1. Navigation is stable and boring in the good sense; content can be expressive, navigation cannot.
2. Primary hierarchy comes from spacing, typography and layer/elevation before borders or color.
3. Large icons are semantic anchors, not decoration. Every icon must answer what destination/action it represents.
4. Avoid glass everywhere. Translucent/material effects belong to navigation/temporary controls, not every card.
5. Main task controls remain prominent and near the active content; destructive controls are visually secondary.
6. Lists remain information-dense enough for desktop use; One UI-sized touch targets do not mean phone-sized rows.
7. Settings use familiar Windows information architecture with Apple-grade spacing/copy polish.
8. Motion communicates state/continuity, stays short, and respects reduced-motion/accessibility policy.
9. Light/dark/high-contrast semantics are token-driven; feature QML must not invent arbitrary colors.
10. KO/EN strings are designed together; truncation is a layout bug, not a translation problem.

## Runtime implication

Sprint 10 keeps UI outside the Core Job Object so a UI crash does not stop downloads. The visual shell
can restart and reconnect to the same authoritative Core projection without changing job semantics.
