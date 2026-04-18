# Recipe Site Research

## Sites

| Site | URL | Content | Tier |
|---|---|---|---|
| Serious Eats | https://www.seriouseats.com | Food + drink | 1 |
| Bon Appétit | https://www.bonappetit.com | Food + drink | 1 |
| NYT Cooking | https://cooking.nytimes.com | Food + drink | 1 |
| Liquor.com | https://www.liquor.com | Drinks focused | 1 |
| Punch | https://punchdrink.com | Drinks focused | 1 |
| Difford's Guide | https://www.diffordsguide.com | Drinks focused | 1 |
| Food Network | https://www.foodnetwork.com | Food + drink | 2 |
| Epicurious | https://www.epicurious.com | Food + drink | 2 |
| Food & Wine | https://www.foodandwine.com | Food + drink | 2 |
| The Kitchn | https://www.thekitchn.com | Food + drink | 2 |
| Imbibe Magazine | https://imbibemagazine.com | Drinks focused | 2 |
| Martha Stewart | https://www.marthastewart.com | Food + drink | 3 |
| Simply Recipes | https://www.simplyrecipes.com | Food + drink | 3 |
| Tasting Table | https://www.tastingtable.com | Food + drink | 3 |

**Note:** Even "drinks focused" sites like Liquor.com carry some food recipes (e.g. [ham deviled eggs](https://www.liquor.com/ham-deviled-eggs-recipe-5115303)), so all sites need drink detection — none can be assumed 100% drinks.

**Excluded:** Saveur — mixed Food + drink site, but no structured way in JSON-LD to determine if a recipe is for drink/cocktail (no recipeCategory, no breadcrumb, no relevant keywords). It's a 3rd tier site, so not worth the hassle.

## Drink Detection in JSON-LD (Food + Drink sites only)

How each site signals that a recipe is a drink/cocktail in its JSON-LD structured data.

| Site | Recipe | URL | `recipeCategory` | `breadcrumb` | `keywords` |
|---|---|---|---|---|---|
| Serious Eats | Margarita | https://www.seriouseats.com/classic-margarita-recipe-tequila-cocktail | `Tequila` | Recipes By Course > Drinks > Cocktails > Tequila | cocktail, drink, margarita, tequila |
| Serious Eats | Negroni | https://www.seriouseats.com/negroni-cocktail-recipe-gin-campari-vermouth | `Gin, Cocktail` | Recipes By Course > Drinks > Cocktails > Gin | cocktail, gin, negroni, campari |
| Bon Appétit | Margarita Without Triple Sec | https://www.bonappetit.com/recipe/margarita | — | — | cocktail, margarita, tequila, drinks |
| Bon Appétit | Negroni | https://www.bonappetit.com/recipe/negroni-2 | — | — | cocktail, gin, campari, drinks |
| NYT Cooking | Perfect Manhattan | https://cooking.nytimes.com/recipes/1026251-perfect-manhattan | `cocktails` | — | whiskey, vermouth |
| NYT Cooking | The Boulevardier | https://cooking.nytimes.com/recipes/1015308-the-boulevardier | `brunch, easy, cocktails` | — | bourbon, campari, vermouth |
| Food Network | Negroni | https://www.foodnetwork.com/recipes/food-network-kitchen/negroni-recipe-2105738 | — | Home > Recipes | `Mixed Drink Recipes` |
| Food Network | Classic Mojito | https://www.foodnetwork.com/recipes/food-network-kitchen/classic-mojito-13160582 | `beverage` | Home > Recipes > Drinks > Classic Mojito | `Mixed Drink Recipes, Mojito Recipes` |
| Epicurious | Classic Margarita | https://www.epicurious.com/recipes/food/views/the-classic-margarita-238570 | — | — | cocktail, margarita, beverages |
| Epicurious | Negroni | https://www.epicurious.com/recipes/food/views/negroni-351597 | — | — | cocktail, negroni, beverages |
| Food & Wine | Royal Bermuda Yacht Club | https://www.foodandwine.com/royal-bermuda-yacht-club-cocktail-recipe-11947102 | `Appetizer, Beverage` | Drinks > Cocktails > Rum Cocktails | — |
| Food & Wine | Frisco Cocktail | https://www.foodandwine.com/frisco-cocktail-recipe-11946605 | `Brunch, Beverage` | Drinks > Cocktails > Whiskey & Bourbon Cocktails | — |
| The Kitchn | Espresso Martini | https://www.thekitchn.com/espresso-martini-cocktail-recipe-23682794 | `Beverage, Cocktail` | — | beverages, cocktails |
| The Kitchn | Negroni | https://www.thekitchn.com/negroni-recipe-23655515 | `Beverage, Cocktail` | Home > Recipes > Beverages > Cocktails | beverages, cocktails |
| Martha Stewart | Margarita | https://www.marthastewart.com/1008032/margarita | `Cocktail` | Food & Cooking > Recipes > Drink Recipes > Cocktail Recipes | margarita |
| Martha Stewart | Pomegranate Cosmopolitan | https://www.marthastewart.com/1008081/pomegranate-cosmopolitans | `Cocktail` | Food & Cooking > Recipes > Drink Recipes > Cocktail Recipes | Cocktails, Vodka |
| Simply Recipes | Mojito Cocktail | https://www.simplyrecipes.com/recipes/mojito/ | `Drink, Cocktail` | Recipes > Drinks > Cocktails | Drink, mojito |
| Simply Recipes | Godfather Cocktail | https://www.simplyrecipes.com/godfather-cocktail-recipe-6544862 | `Cocktail` | Recipes > Drinks | cocktail, scotch |
| Tasting Table | Classic Negroni | https://www.tastingtable.com/688194/classic-negroni-cocktail-recipe/ | `drink` | — | Easy |
| Tasting Table | Smooth Old Fashioned | https://www.tastingtable.com/923635/smooth-old-fashioned-cocktail-recipe/ | `beverage` | — | traditional, citrusy |

### Summary

| Site | Best signal | Detection method |
|---|---|---|
| Serious Eats | breadcrumb | Breadcrumb contains `Drinks` or `Cocktails` |
| Bon Appétit | keywords | `keywords` contains `cocktail` or `drinks` (no category or breadcrumb) |
| NYT Cooking | recipeCategory | `recipeCategory` contains `cocktails` |
| Food Network | breadcrumb + keywords | Breadcrumb contains `Drinks`; keywords contain `Mixed Drink` |
| Epicurious | keywords | `keywords` contains `cocktail` or `beverages` (no category or breadcrumb) |
| Food & Wine | breadcrumb + recipeCategory | Both `Beverage` in category and `Drinks > Cocktails` in breadcrumb |
| The Kitchn | recipeCategory | `recipeCategory` contains `Cocktail` and/or `Beverage` |
| Martha Stewart | recipeCategory + breadcrumb | `Cocktail` in category; `Drink Recipes > Cocktail Recipes` in breadcrumb |
| Simply Recipes | recipeCategory + breadcrumb | `Cocktail`/`Drink` in category; `Drinks` in breadcrumb |
| Tasting Table | recipeCategory | `drink` or `beverage` in category (weak — no `cocktail` keyword) |
