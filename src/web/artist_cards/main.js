// Renders one card per period (month or year) and reports clicks as a "clicked" trigger.
// Text is set via textContent (never innerHTML), so artist and track names
// from the database can't inject markup.

function line(className, text) {
    const span = document.createElement("span");
    span.className = className;
    span.textContent = text;
    return span;
}

export default function (component) {
    const { data, parentElement, setTriggerValue } = component;

    let strip = parentElement.querySelector(".strip");
    if (!strip) {
        const wrap = document.createElement("div");
        wrap.className = "wrap";
        strip = document.createElement("div");
        strip.className = "strip";
        wrap.appendChild(strip);
        parentElement.appendChild(wrap);
    }
    strip.replaceChildren();

    for (const m of data.items) {
        const tile = document.createElement("button");
        tile.type = "button";
        tile.className = "tile";
        if (m.id === data.selected) tile.classList.add("selected");

        if (!m.artist) {
            tile.classList.add("empty");
            tile.disabled = true;
            tile.title = `${m.name}: no data`;
        } else {
            tile.title = `${m.name}: ${m.artist}`;
            tile.onclick = () => setTriggerValue("clicked", m.id);
        }

        if (m.image) {
            const img = document.createElement("img");
            img.src = m.image;
            img.alt = m.artist;
            img.loading = "lazy";
            tile.appendChild(img);
        }

        tile.appendChild(line("badge", m.label));

        if (m.artist) {
            const info = document.createElement("span");
            info.className = "info";
            info.append(
                line("artist", m.artist),
                line("minutes", `${m.minutes.toLocaleString("en-US")} min · ${m.share}%`),
            );
            if (m.top_track) info.append(line("song", `♫ ${m.top_track}`));
            tile.appendChild(info);
        }

        strip.appendChild(tile);
    }

    // On the swipeable phone layout, center the selected card. Only the strip's
    // own scroll position changes; scrollIntoView would also scroll the page.
    const selected = strip.querySelector(".tile.selected");
    if (selected && strip.scrollWidth > strip.clientWidth) {
        strip.scrollLeft = selected.offsetLeft - (strip.clientWidth - selected.clientWidth) / 2;
    }
}
