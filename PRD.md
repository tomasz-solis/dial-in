# Dial In - Product Requirements Document (PRD)

**Version:** 1.0  
**Author:** Tomasz Solis  
**Status:** Draft  
**Product Type:** SaaS / Internal Tool  
**Target Market:** Independent Cafés, Specialty Coffee Shops, Bakeries, Brunch Restaurants  

---

## 1. Executive Summary
Dial In is a lightweight prep-planning assistant designed for independent cafés and bakeries. The product helps operators answer one operational question:

> **How much food should I prepare tomorrow?**

Using historical sales, weather forecasts, seasonality, local events, and operational signals, Dial In recommends daily preparation quantities while minimizing:
* Food stockouts
* Lost revenue
* Customer disappointment
* Food waste

Unlike traditional BI tools, Dial In focuses on decisions rather than reporting. The goal is not forecasting; the goal is helping operators make better preparation decisions with almost zero administrative overhead.

---

## 2. Problem Statement
Independent cafés often rely on intuition when deciding how much food to prepare. This approach breaks down when:
* Weather changes unexpectedly
* Tourism fluctuates
* Local events occur
* Seasonality shifts
* Weekends behave differently than weekdays

The result is usually one of two outcomes:

### Under-Preparation
Too little food is prepared, and items sell out early.
* **Consequences:** Lost sales, reduced average order value, frustrated customers, and operational stress.
* **Example:** Croissants sold out at 11:15, but demand remained until 14:00. Significant revenue was lost.

### Over-Preparation
Too much food is prepared.
* **Consequences:** Food waste, reduced margins, and unnecessary labor costs.
* **Example:** 15 premium pastries discarded at the end of the day.

---

## 3. Product Vision
Dial In becomes the operational copilot for independent cafés. Each evening or morning, operators receive a recommendation similar to a weather forecast:

**Tomorrow's Forecast & Recommendation Example:**
* **Expected Traffic:** 190–220 drinks
* **Recommended Prep:**
  * Sweet pastries: 54
  * Savory pastries: 31
* **Risk Level:** High demand expected
* **Drivers:** Sunny weather, Saturday, Local market

The user should be able to obtain all necessary information in under 30 seconds.

---

## 4. Product Principles
* **Principle 1: Low friction beats model accuracy.** A slightly less accurate model used daily is better than a highly accurate model requiring constant maintenance.
* **Principle 2: Every manual input must justify itself.** If data can be automated, automate it.
* **Principle 3: Recommendations over analytics.** The user wants answers, not dashboards.
* **Principle 4: Build for small businesses.** Assume no data team, no dedicated analyst, no inventory manager, and limited technical expertise.

---

## 5. Target Customer

### Primary
**Independent Specialty Coffee Shops**
* **Characteristics:** 1 location, 2–10 employees, owner-operated, fresh food preparation.
* **Examples:** Specialty cafés, artisan bakeries, brunch cafés.

### Secondary
**Small Multi-Location Operators**
* **Characteristics:** 2–10 locations, centralized planning, need location-level recommendations.

---

## 6. Success Metrics

### Business Metrics
* Reduce stockouts by 20%
* Reduce food waste by 15%
* Increase food revenue by 10%
* Increase average order value

### Product Metrics
* Weekly active usage > 80%
* Daily completion rate > 90%
* Average daily interaction < 30 seconds
* Average onboarding < 15 minutes

---

## 7. Core User Journey

### End of Day
Operator enters:
* Sweet pastries prepared today
* Savory pastries prepared today
* **Time required:** 10 seconds

### Morning
* Operator opens Dial In.
* Views recommendation.
* Closes app.
* **Time required:** 15 seconds

**Total Daily Effort Target:** Less than 30 seconds.

---

## 8. MVP Scope

* **Daily Recommendation Engine:** Generate recommendations for sweet and savory pastries. Display recommended quantity, expected demand range, confidence level, and key demand drivers.
* **Traffic Forecast:** Predict daily customer traffic using drink sales as a proxy. (Output example: 180–210 drinks).
* **Demand Forecast:** Predict sweet pastry and savory pastry demand using historical sales, traffic forecasts, weather, events, and seasonality.
* **Risk Detection:** Identify a high probability of stockouts. (Example: Current recommendation is 40 sweet pastries, but estimated demand is 55 -> Risk: High).

---

## 9. Data Collection Strategy

### Philosophy
Data collection should be nearly invisible. The user should never feel like they are maintaining software.

### Required Daily Inputs
* **Sweet Prepared:** Number prepared that day (e.g., 45).
* **Savory Prepared:** Number prepared that day (e.g., 25).

### Imported Data (via POS integration)
* Drinks Sold (Daily count)
* Sweet Pastries Sold (Daily count)
* Savory Pastries Sold (Daily count)

### Automatic Data
* **Weather:** Temperature, rainfall, weather conditions, wind, and forecast.
* **Calendar:** Weekday, month, holidays, school holidays, and bridge days.
* **Seasonality:** Month, quarter, tourism season.

---

## 10. Data Model

### Daily Metrics Table
* `date`
* `drinks_sold`
* `sweet_pastries_sold`
* `savory_pastries_sold`
* `sweet_prepared`
* `savory_prepared`

### Weather Table
* `date`
* `temperature`
* `rainfall`
* `weather_condition`
* `wind_speed`

### Events Table
* `date`
* `event_name`
* `event_type`
* `impact_score`

### Forecast Table
* `date`
* `forecast_drinks`
* `forecast_sweet`
* `forecast_savory`
* `confidence`
* `generated_at`

---

## 11. Forecasting Strategy

* **V1: Rules-Based Forecasting**
  * *Inputs:* Day of week, month, weather, historical averages.
  * *Advantages:* Explainable, fast, stable.
* **V2: Machine Learning**
  * *Models:* LightGBM, XGBoost.
  * *Features:* Historical sales, weather, events, seasonality, traffic patterns.
* **V3: Probabilistic Forecasting**
  * *Output:* Instead of a single number (e.g., "Prepare 40"), provide a range (e.g., "Prepare 38–47, Confidence: High").

---

## 12. Handling Censored Demand

### Problem
Sales do not always equal demand. If you prepare 40 pastries and sell 40 pastries, you sold out, but true demand remains unknown (could be 50, 60, or 70).

### Solution
Estimate true demand using:
* Similar historical days
* Traffic volume and drink sales
* Weather and event patterns

Dial In should estimate potential lost sales, potential missed revenue, and provide a recommended adjustment.

---

## 13. Forecast Features

* **Traffic Signals:** Drinks sold, previous week, previous month, rolling averages.
* **Weather Signals:** Rain, temperature, wind, outdoor seating conditions.
* **Event Signals:** Market days, marathons, festivals, concerts, sporting events.
* **Seasonal Signals:** Summer, tourism season, public holidays, Christmas period.

---

## 14. UX Requirements
* **Mobile First:** Most owners will access the tool from a phone.
* **Fast:** Page load under 3 seconds.
* **Simple:** No dashboards on startup, no reports on startup, and no confusing analytics terminology.

---

## 15. Future Roadmap
* **Phase 2:** Hourly demand forecasting.
* **Phase 3:** Staffing recommendations (e.g., Expected traffic suggests an additional employee from 10:00–13:00).
* **Phase 4:** Ingredient forecasting (e.g., Expected croissants require specific amounts of butter, flour, chocolate).
* **Phase 5:** Inventory optimization.
* **Phase 6:** Multi-location benchmarking.

---

## 16. Future Integrations
* **POS Systems:** Square, Toast, Lightspeed, Shopify POS, Custom CSV imports.
* **Calendar & External Feeds:** Google Calendar, Google Weather APIs, Local event feeds.

---

## 17. Non-Goals
Dial In is explicitly **not**:
* An inventory system
* An accounting system
* A POS replacement
* A workforce management platform
* A BI platform or general reporting tool

---

## 18. Positioning
Dial In helps independent cafés prepare for tomorrow. It combines operational intuition with data-driven recommendations to answer a single question: 

**“What should we prepare tomorrow?”** Everything else is secondary.
