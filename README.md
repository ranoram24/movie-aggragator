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

**If you already know what you want, type it.** The search box filters the grid
as you type, in Hebrew or English, and matches how people actually type rather
than how the cinemas spell things: word order does not matter, so *אריות מלך*
finds *מלך האריות*, and the spelling drift between chains does not either.

## A film

Opening a card gives the poster, synopsis, and the facts worth knowing before
committing an evening: genre, runtime, age rating, and the original language
(**שפת מקור**).

Below that, every cinema showing it, each with its screenings grouped by day —
today, tomorrow, then by weekday. Two filters narrow it when a popular film is
showing a hundred times:

- **by chain**, if you have a membership or a preferred cinema
- **by audio language**, to separate the Hebrew dub from the original
- **by city**, typed in — and it respects the other two, so narrowing to one
  chain and then typing a city will never show you a different chain's cinema
  in that city

City search knows the abbreviations the cinemas file their branches under, so
*ראשון לציון* finds the one listed as *ראשל"צ*, and it searches addresses as
well as names, which is the only way to find the Tel Aviv cinemas that are named
after their neighbourhood.

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

## Putting it in your calendar

Tapping a time opens the checkout in a new tab and leaves a question behind in
this one: **להוסיף ליומן?** — with that exact screening's film, cinema, date and
time, and two ways to keep it.

**Google Calendar** is two taps and the event is synced to every device you own.
**קובץ** downloads a calendar file instead, which is slower but carries a
**reminder two hours before** — roughly when you need to start thinking about
leaving. The split is not a design preference: Google's prefill screen has no
way to set a reminder, so an event added that way gets whatever default your
account uses. The sheet says so, under the buttons.

The event runs for the film's length plus twenty minutes of trailers, so the
block in your calendar covers the time you are actually in the building rather
than only the running time.

The file route works with whatever calendar you use and needs no account.
Neither route blocks the booking: the checkout opens first either way, and the
question waits for you when you come back. Dismissing it is one tap.

## Coming to digital

A film that is not out at home yet says when it will be — *דיגיטל 17/11/2026*.
One that is already out just says so — *זמין בדיגיטל* — because the date only
ever answered "how long do I wait", and once a film is available there is
nothing left to wait for. It sits with the runtime and the age rating, in the
same quiet type.

That is the whole feature. The app does not tell you a film is about to be
cheaper at home, does not count down, and does not suggest waiting. Whether two
days is worth waiting for depends on who is asking, and the app is not the one
asking. It states the fact; the conclusion is yours.

## Coverage

39 cinemas across five chains — Cinema City, Hot Cinema, Planet, Movieland and
Lev Cinema — refreshed through the day. The chains publish the following week's
schedule on Tuesday afternoons, and the app follows within hours.

Past screenings disappear as the evening goes on, so what you see is what you
can still get to.
