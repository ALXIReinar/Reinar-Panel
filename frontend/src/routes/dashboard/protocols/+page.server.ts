import { FetchProtocols } from "$lib/api/protocols";
import type { PageServerLoad } from "./$types";
import { PROTOCOLS_LIMIT_COOKIE, parseLimit } from "$lib/constants";

export const load: PageServerLoad = async (event) => {
    const limit = parseLimit(event.cookies.get(PROTOCOLS_LIMIT_COOKIE));
    let protocols = await FetchProtocols(undefined, limit);

    return {
        protocols,
        limit,
    };
}
