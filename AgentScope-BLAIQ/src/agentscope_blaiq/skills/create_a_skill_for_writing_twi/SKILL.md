---
name: create_a_skill_for_writing_twi
description: create a skill for writing Twitter threads about renewable energy products
target_agent: text_buddy, content_director
---

### Purpose
To generate an engaging, multi-tweet Twitter thread that explains the value and benefits of a specific renewable energy product, based on an evidence brief.

### Rules
1.  **Deconstruct the Evidence**: Identify the product name, its single most important benefit, 2-3 secondary benefits, and any data points or statistics.
2.  **Tweet 1: The Hook**: Start with a powerful question or a surprising statistic from the evidence to grab attention. Do not reveal the product name yet. End with a "thread" emoji (🧵) or a hint that there's more to come.
3.  **Tweet 2: The Reveal**: Introduce the product by name. State its primary function and unique value proposition.
4.  **Tweets 3-4: The Benefits**: Dedicate one tweet to each key benefit. Use the data/statistics from the evidence brief. Use relevant emojis (e.g., 💰 for cost savings, 🌍 for environmental impact).
5.  **Tweet 5: The CTA (Call to Action)**: The final tweet must encourage action. This could be asking a question to drive engagement, or directing users to a link for more information (use a placeholder like `[Link to Product]`).
6.  **Formatting**:
    *   All tweets must be under 280 characters.
    *   Number each tweet in the format `(n/N)`.
    *   Include 2-3 relevant hashtags in the final tweets of the thread (e.g., #RenewableEnergy, #Solar, #CleanTech, #EnergySavings).

### Output Format
The skill must output a JSON object containing a single key, "thread", which holds a list of strings. Each string is a single, formatted tweet.

```json
{
  "thread": [
    "Tweet 1 text (Hook)",
    "Tweet 2 text (Product Reveal)",
    "Tweet 3 text (Benefit 1)",
    "Tweet 4 text (Benefit 2)",
    "Tweet 5 text (CTA)"
  ]
}
```

### Examples

**Example 1: High-Efficiency Solar Panels**

*   **Input Evidence**: Product: "SunPower Equinox Solar Panels". Facts: "40% more efficient than conventional panels", "Reduces electricity bill by up to 90%", "Sleek, low-profile design".
*   **Generated Output**:
    ```json
    {
      "thread": [
        "What if your roof could pay your electricity bill? For most homeowners, it's not a dream. It's a reality. 🧵 (1/5)",
        "Meet the SunPower Equinox solar system. It’s not just a panel; it’s a complete home energy solution designed for maximum power and style. ☀️ (2/5)",
        "The Equinox system is 40% more efficient than conventional panels, meaning you generate more power from less space. More power = more savings. 💰 (3/5)",
        "On average, homeowners can reduce their electricity bills by up to 90%. Think about what you could do with that extra money every month. (4/5)",
        "Ready to declare energy independence and shrink your carbon footprint? Learn more about the SunPower Equinox here: [Link to Product] #Solar #RenewableEnergy #CleanTech (5/5)"
      ]
    }
    ```

**Example 2: Smart Water Heater**

*   **Input Evidence**: Product: "Aquanta Smart Water Heater Controller". Facts: "Makes your existing water heater smart", "Saves up to 30% on water heating costs", "Control via mobile app", "Provides maintenance alerts".
*   **Generated Output**:
    ```json
    {
      "thread": [
        "Your water heater is the second biggest energy hog in your home. What if you could make it smart and cut that cost by a third? Here's how 👇 (1/4)",
        "The Aquanta controller retrofits to your *existing* water heater, turning it into a smart, energy-saving appliance. No need to buy a whole new tank! 💧 (2/4)",
        "It learns your usage patterns and heats water only when you need it, saving up to 30% on water heating costs. Plus, you can control it from anywhere with the app! #SmartHome #EnergySavings (3/4)",
        "Stop heating water when you're not home. Upgrade your dumb water heater and start saving today! Find out more: [Link to Product] #DIY #Tech (4/4)"
      ]
    }
    ```### Purpose
To generate an engaging, multi-tweet Twitter thread that explains the value and benefits of a specific renewable energy product, based on an evidence brief.

### Rules
1.  **Deconstruct the Evidence**: Identify the product name, its single most important benefit, 2-3 secondary benefits, and any data points or statistics.
2.  **Tweet 1: The Hook**: Start with a powerful question or a surprising statistic from the evidence to grab attention. Do not reveal the product name yet. End with a "thread" emoji (🧵) or a hint that there's more to come.
3.  **Tweet 2: The Reveal**: Introduce the product by name. State its primary function and unique value proposition.
4.  **Tweets 3-4: The Benefits**: Dedicate one tweet to each key benefit. Use the data/statistics from the evidence brief. Use relevant emojis (e.g., 💰 for cost savings, 🌍 for environmental impact).
5.  **Tweet 5: The CTA (Call to Action)**: The final tweet must encourage action. This could be asking a question to drive engagement, or directing users to a link for more information (use a placeholder like `[Link to Product]`).
6.  **Formatting**:
    *   All tweets must be under 280 characters.
    *   Number each tweet in the format `(n/N)`.
    *   Include 2-3 relevant hashtags in the final tweets of the thread (e.g., #RenewableEnergy, #Solar, #CleanTech, #EnergySavings).

### Output Format
The skill must output a JSON object containing a single key, "thread", which holds a list of strings. Each string is a single, formatted tweet.

```json
{
  "thread": [
    "Tweet 1 text (Hook)",
    "Tweet 2 text (Product Reveal)",
    "Tweet 3 text (Benefit 1)",
    "Tweet 4 text (Benefit 2)",
    "Tweet 5 text (CTA)"
  ]
}
```

### Examples

**Example 1: High-Efficiency Solar Panels**

*   **Input Evidence**: Product: "SunPower Equinox Solar Panels". Facts: "40% more efficient than conventional panels", "Reduces electricity bill by up to 90%", "Sleek, low-profile design".
*   **Generated Output**:
    ```json
    {
      "thread": [
        "What if your roof could pay your electricity bill? For most homeowners, it's not a dream. It's a reality. 🧵 (1/5)",
        "Meet the SunPower Equinox solar system. It’s not just a panel; it’s a complete home energy solution designed for maximum power and style. ☀️ (2/5)",
        "The Equinox system is 40% more efficient than conventional panels, meaning you generate more power from less space. More power = more savings. 💰 (3/5)",
        "On average, homeowners can reduce their electricity bills by up to 90%. Think about what you could do with that extra money every month. (4/5)",
        "Ready to declare energy independence and shrink your carbon footprint? Learn more about the SunPower Equinox here: [Link to Product] #Solar #RenewableEnergy #CleanTech (5/5)"
      ]
    }
    ```

**Example 2: Smart Water Heater**

*   **Input Evidence**: Product: "Aquanta Smart Water Heater Controller". Facts: "Makes your existing water heater smart", "Saves up to 30% on water heating costs", "Control via mobile app", "Provides maintenance alerts".
*   **Generated Output**:
    ```json
    {
      "thread": [
        "Your water heater is the second biggest energy hog in your home. What if you could make it smart and cut that cost by a third? Here's how 👇 (1/4)",
        "The Aquanta controller retrofits to your *existing* water heater, turning it into a smart, energy-saving appliance. No need to buy a whole new tank! 💧 (2/4)",
        "It learns your usage patterns and heats water only when you need it, saving up to 30% on water heating costs. Plus, you can control it from anywhere with the app! #SmartHome #EnergySavings (3/4)",
        "Stop heating water when you're not home. Upgrade your dumb water heater and start saving today! Find out more: [Link to Product] #DIY #Tech (4/4)"
      ]
    }
    ```