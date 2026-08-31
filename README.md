# On Cinema

Everything showing in Israeli cinemas tonight, on one screen, in Hebrew.

Five chains publish their schedules separately, so finding a film near you
normally means checking five sites and holding the results in your head. On
Cinema collects all of them and answers the question directly: what is playing,
where, when, and in what language.

Live at **[on-cinema-now.fly.dev](https://on-cinema-now.fly.dev)** — built for a
phone, right-to-left throughout.

## Browsing

The home screen is a grid of posters, one card per film. If you allow location
access, films are ordered by how close their nearest cinema is, so what is
actually reachable comes first. Refusing is a supported answer, not a dead end:
the same grid appears ordered by how widely each film is showing. The app never
waits on the permission dialog before rendering.

**A film gets one card, not one per chain.** The same title arrives from five
sources spelled five ways, and a Hebrew dub is often listed as a separate film
from the subtitled original. Those are collapsed together, so *Spider-Man* is a
single card whether it is playing at Planet, Cinema City, or both, dubbed or
not.

## A film

Opening a card gives the poster, synopsis, and the facts worth knowing before
committing an evening: genre, runtime, age rating, and the original language
(**שפת מקור**).

Below that, every cinema showing it, each with its screenings grouped by day —
today, tomorrow, then by weekday. Two filters narrow it when a popular film is
showing a hundred times:

- **by chain**, if you have a membership or a preferred cinema
- **by audio language**, to separate the Hebrew dub from the original

## Showtimes

Each showtime is a button that opens that chain's checkout **for that exact
screening** — the right film, cinema, hall and time, already selected. Not the
cinema's home page.

A showtime is labelled with its audio language only when it is dubbed. An
unlabelled screening is the film in its original language, which is the same
convention the cinemas use in their own listings — marking every screening would
put text on most of them to say nothing had changed. Non-standard halls are
marked too, so IMAX, VIP and 4DX are visible before you tap.

Each cinema also has a **נווט לקולנוע** button that opens Google Maps directions
from where you are to that cinema, by name.

## Coverage

39 cinemas across five chains — Cinema City, Hot Cinema, Planet, Movieland and
Lev Cinema — refreshed through the day. The chains publish the following week's
schedule on Tuesday afternoons, and the app follows within hours.

Past screenings disappear as the evening goes on, so what you see is what you
can still get to.
