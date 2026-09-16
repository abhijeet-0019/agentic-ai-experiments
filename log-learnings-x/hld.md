node1 -> generate_post
node2 -> human_review

edge1 -> start --> generate_post
edge2 -> generate_post --> human_review
edge3 -> human_review --> CONDITIONA(
	if 'approved':
		--> finish
	else:
		--> generate_post
	
	) -- interrupt before

=======================================

state:
	post_gen_status: True/False --- bool
	post_review_status: PASS/FAIL --- string
	re_gen_count: 0-5 --- int
	input_text: -- string
	review_msg: {} --- append/reducer - to be converted to proper format and and summarize in case of repetitive msg OR large msg, APPEND only so that along with the input msg the response & and review also remian in the context
	output: -- {} --- add/replace only, json because in case the response is larger then due to the single post limit of 280 chars, we have to move from single post to multiple posts (i.e.threads we have in x/twitter)

=======================================

SYSTEM_MSG/PROMPT: """you are a techie have passion and  professiciency in system design, ai architectures, aws architectures, python, etc. with 10+ years of working experices, you are also good with twitter/x context/post writting, know how to write engaging and interesting post and threads about the topics of your domain. 
Here, you have an objective converting the input given by the user into twitter/x post(and if content demands give threads in the output in proper format):
here are some rules about writting:
- keep it human, use short sentences, write clearly in simply english.
- be passionate.
- if some placeholders are required to be filled by the user keep the necessay space.
- remember the max number of chars that the post can have is 280, so if the post is going beyond that, convert that to thread (multiple posts)
- dont write essay on the topics with the concpts that user dont know, only include thse with the user have given in tht inpout, you can refine to include the content that you feel user is aware of but somhow missed in the input.
- the objective of this writting is to log the daily work and learnings of the user to be exposed/shared with the communities using x/twitter. to build the online presence and personal brand.
- the obejctive of this build connections, to the ones who are interested in the similar topics, or the ones who are expert in the similar profiles. 

here is the input: {input}

here is the review of the previous response of yours, please update the post/s as per the review instructions of the user
here is the previous response: {last_res}
here is the review by the user on the last response: {last_res}
"""

full_msg():
	input
	review
	last_res

generate_post():

	if state.re_gen_count >4:
		return END --> mgs -- max attemptes exhausted, kindly retry -- here is the snap of our disucssoin so far -- state
	input = state.input_text
	
	full_msg[input] = input
	
	if len.review_msg>0:
		full_msg[review] = state.review_msg[-1]
		full_msg[last_res] = state.output
	
	call_llm(SYSTEM_MSG.append(full_msg)

human_review():
	
	res = input("here is your post/s:")
	if res != "" OR "approved":
		return END
	return generate_post




