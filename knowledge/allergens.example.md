# Allergen and dietary facts - Hotel Aurora

<!--
Copy this to knowledge/allergens.md. This is what `tools/engine.py:
check_allergen()` checks a draft's claims against - the Warden's own
allergen-check docstring explains the rule: a claim is "confirmed" only when
it matches a line below closely (one contains the other, case-insensitive),
not because it sounds plausible. Silence is not confirmation - an unlisted
claim always escalates to a human, on purpose. See docs/safety.md "The five
screening checks".

One fact per line, written the same way you would want it read back to a
guest with a serious allergy. Never write a line you are not certain of -
a wrong "yes" here is exactly the mistake this check exists to catch.
-->

## Confirmed dish facts

- the garden salad is nut-free and dairy-free
- the grilled chicken breast is gluten-free when served without the bread roll
- the vegetable soup is dairy-free and contains celery
- the house dressing is gluten-free and contains sesame
- the breakfast granola contains nuts and oats
- the sourdough bread is made fresh daily and contains gluten
- the pan-seared salmon is dairy-free and shellfish-free
- the children's menu pasta contains gluten and dairy

## What the kitchen will not confirm in writing

- Any "completely" or "guaranteed" allergen-free claim about a dish that
  shares a kitchen and fryer with nut, shellfish or gluten ingredients - our
  kitchen cannot rule out cross-contact, so a claim like that must always go
  to the head chef directly, not into an AI-drafted reply.
- Anything about the seafood tasting menu: it is prepared in the same space
  as shellfish and tree nuts, so no blanket "safe for allergy X" claim about
  it should ever be confirmed here.

## Keeping this current

Update this file whenever the kitchen changes a recipe or a supplier. A
change here is the only way a previously-escalated claim starts passing
through automatically - and the only way a previously-safe claim starts
being caught if an ingredient changes.
